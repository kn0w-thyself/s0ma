"""Redaction profile v1 — deterministic, ordered, idempotent (contract §7).

Every piece of free text a person writes into a feedback report passes
through here before it is shown back to them, hashed, or sent: ``summary``,
``expected``, ``actual``, ``details``, and each ``reproduction`` step. The
ten rules of ``docs/contracts/feedback-v1.md`` §7 run **in the frozen
order**, numbering per type across the whole envelope, and produce a counts
map for the ``privacy.redacted`` report.

**This module is frozen.** :data:`REDACTION_PROFILE` is the version handle.
Changing, adding, reordering, or removing a rule — or changing a
placeholder's spelling — requires a re-freeze of the contract under its §13
change control, not an edit here. The placeholder spellings are load-bearing
across repositories: the control plane's sensitive-content screen neutralizes
these exact strings so correctly redacted text can never be refused
(contract r4 ruling 6), which is only true if this side emits them byte for
byte.

Idempotency is structural, not aspirational. Every pattern is
placeholder-aware, so redacting redacted text is a fixed point:
``redact(redact(t)[0])[0] == redact(t)[0]``, with an empty counts map on the
second pass because nothing was left to remove.

Rulings this implementation makes where §7 leaves room (all pinned by
``tests/test_feedback_redact.py``):

* **Rule 4 before rule 5.** ``git@github.com:org/repo.git`` reaches the
  email rule first and its host half becomes ``<EMAIL_n>``, leaving the
  repository path as residue. The frozen order says so; rule 5 still catches
  remotes whose host has no dot (``git@localhost:org/repo.git``), and a
  scheme-bearing URL collapses whole even when rule 4 already took its host,
  because rule 5 reads a placeholder as part of the URL token.
* **Rule 6 is the enumeration.** POSIX matching is scoped to the three roots
  §7 lists — ``/Users/``, ``/home/``, ``/private/`` — while the Windows forms
  stay general, exactly as §7 writes them. That asymmetry is deliberate: on
  POSIX those are the roots that carry a person's name, and a broader rule
  would swallow ``/api/feedback`` and ``/usr/bin/env`` out of a bug report,
  destroying the very detail the report exists to carry. Widening it is a
  contract change, not a code change — see :data:`POSIX_PATH_ROOTS`.
* **Counts are occurrences, keyed by placeholder type.** Three appearances
  of one path count three, under ``paths`` — the count answers "how much was
  removed", while the numbering answers "how many distinct things".
* **The same value keeps the same placeholder** for the whole pass
  (contract §7.1), so a report stays readable: two mentions of one path are
  visibly the same path.
* **Rule 9's false-positive bound.** Nothing shorter than
  :data:`ENTROPY_MIN_CHARS` characters is ever considered, and the threshold
  of :data:`ENTROPY_MIN_BITS` bits per character means a 20-character string
  cannot reach it at all (log2(20) ≈ 4.32) — the rule wakes up around 23
  characters of near-maximal diversity. Hex digests top out at 4 bits per
  character, so a SHA-256 in a bug report survives intact.

Rule 3 is implemented as **re-frozen in contract revision r5**: the prefix
before the keyword is optional, so ``PASSWORD=hunter2`` and ``TOKEN=abc`` are
caught alongside ``DB_PASSWORD=…``. (The original pattern opened with
``[A-Z]``, which consumed the keyword's own first letter; a variable named
exactly the keyword escaped rule 3 and, at low entropy, rule 9 too. The r5
row of §13 carries the ruling and binds the control-plane screen equally.)
Profile ``v1`` is still the handle — r5 amended a rule inside it under §13
change control, which is exactly the route §7.1 requires.

One bound survives any re-freeze, and is pinned by name in the corpus:
**homoglyphs defeat a deterministic profile.** ``раssword`` in Cyrillic is
not ``password``. The preview-and-approve step, not this module, is the
backstop — which is why nothing is ever sent without the reporter reading the
redacted text first.

Everything here is pure: no clock, no network, no filesystem. The only
machine facts consulted are the current username and hostname (rules 7 and
8), read once per pass and overridable by argument so tests are
deterministic.
"""

from __future__ import annotations

import getpass
import math
import platform
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.feedback.model import FeedbackEnvelope, FeedbackPrivacy

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "COUNT_KEYS",
    "ENTROPY_MIN_BITS",
    "ENTROPY_MIN_CHARS",
    "NEUTRAL_MARKER",
    "PLACEHOLDER_PATTERN",
    "POSIX_PATH_ROOTS",
    "REDACTION_PROFILE",
    "REDACTED_TEXT_FIELDS",
    "local_hostname",
    "local_username",
    "neutralize",
    "redact",
    "redact_envelope",
    "shannon_entropy",
]

#: The frozen profile handle (contract §7.1). Written into ADR-004 and the
#: contract doc; a rule change means a new value **and** a re-freeze.
REDACTION_PROFILE = "v1"

#: Free-text envelope fields, in contract §3.1 order. Numbering walks them
#: in this order, with ``reproduction`` expanded in index order.
REDACTED_TEXT_FIELDS: tuple[str, ...] = (
    "summary",
    "expected",
    "actual",
    "details",
    "reproduction",
)

# ---------------------------------------------------------------------------
# Counts (``privacy.redacted``) — one key per placeholder type
# ---------------------------------------------------------------------------

#: Rules 1, 2, 3 and 9 all emit ``<SECRET_REDACTED>`` and all count here.
SECRETS = "secrets"
EMAILS = "emails"
URLS = "urls"
PATHS = "paths"
USERNAMES = "usernames"
HOST_IDS = "host_ids"
TRACE_FRAMES = "trace_frames"

#: Every key that can appear in a counts map. A type that removed nothing is
#: absent, never present as a zero.
COUNT_KEYS: tuple[str, ...] = (
    SECRETS,
    EMAILS,
    URLS,
    PATHS,
    USERNAMES,
    HOST_IDS,
    TRACE_FRAMES,
)

# ---------------------------------------------------------------------------
# Placeholders (contract §7 — exact spellings, load-bearing across repos)
# ---------------------------------------------------------------------------

SECRET_PLACEHOLDER = "<SECRET_REDACTED>"
USER_PLACEHOLDER = "<USER>"
TRACE_PLACEHOLDER = "<TRACE_FRAME>"

#: Characters a kept basename may carry (rule 6's ``<PATH_n:basename>``).
_SAFE_BASENAME_RE = re.compile(r"[A-Za-z0-9._+-]{1,64}")

#: Matches every placeholder this profile can emit. Rules consult it so they
#: never redact their own output — this is where idempotency comes from.
PLACEHOLDER_PATTERN = (
    r"<(?:SECRET_REDACTED|USER|TRACE_FRAME"
    r"|EMAIL_\d+|URL_\d+|HOST_ID_\d+"
    r"|PATH_\d+(?::[A-Za-z0-9._+-]{1,64})?)>"
)
_PLACEHOLDER_RE = re.compile(PLACEHOLDER_PATTERN)

#: Placeholder kinds that carry a number, for continuing a numbering series
#: over text that was already redacted once.
_NUMBERED_RE = re.compile(r"<(?P<kind>EMAIL|URL|HOST_ID|PATH)_(?P<number>\d+)")

#: Guard placed where a rule would otherwise consume a placeholder as if it
#: were the secret it replaced (rules 2 and 3 read a whole token as a value).
_NOT_PLACEHOLDER = f"(?!{PLACEHOLDER_PATTERN})"


#: What a neutralized placeholder becomes. Non-space, so a rule cannot reach
#: across the gap and bind the next word as a value (contract r5 ruling 3
#: forbids deleting them for exactly that reason); non-word, so it cannot
#: join its neighbours into a match that was not there before.
NEUTRAL_MARKER = "~"


def neutralize(text: str, filler: str = NEUTRAL_MARKER) -> str:
    """Substitute *filler* for every profile-v1 placeholder in *text*.

    The control plane runs this before its detection-only port of rules 1–5,
    which is what makes correctly redacted text un-refusable (contract r4
    ruling 6). r5 ruling 3 makes the substitution binding: deleting a
    placeholder would leave ``NAME=`` and let rule 3's ``\\S+`` bind whatever
    word came next. Exposed here so both halves can be shown to agree on
    which strings are placeholders — including the ``<PATH_n:basename>``
    form, which r5 also requires the screen to recognize.
    """
    return _PLACEHOLDER_RE.sub(filler, text)


# ---------------------------------------------------------------------------
# Machine facts (rules 7 and 8)
# ---------------------------------------------------------------------------


def local_username() -> str:
    """This machine's login name, or ``""`` when it cannot be determined."""
    try:
        name = getpass.getuser()
    except (OSError, KeyError):  # pragma: no cover - platform dependent
        name = ""
    if not name:  # pragma: no cover - platform dependent
        try:
            name = Path.home().name
        except (OSError, RuntimeError):
            name = ""
    return name


def local_hostname() -> str:
    """This machine's hostname, or ``""`` when it cannot be determined."""
    try:
        return platform.node()
    except OSError:  # pragma: no cover - platform dependent
        return ""


# ---------------------------------------------------------------------------
# Entropy (rule 9)
# ---------------------------------------------------------------------------

#: Rule 9 never looks at anything shorter (the documented false-positive
#: bound: identifiers of 19 characters or fewer are untouchable by entropy).
ENTROPY_MIN_CHARS = 20

#: Bits per character at or above which a candidate is treated as a secret.
ENTROPY_MIN_BITS = 4.5


def shannon_entropy(value: str) -> float:
    """Shannon entropy of *value* in bits per character (0.0 when empty)."""
    if not value:
        return 0.0
    total = len(value)
    return -sum(
        (count / total) * math.log2(count / total) for count in Counter(value).values()
    )


# ---------------------------------------------------------------------------
# Pass state — numbering, counts, and the machine facts for one redaction
# ---------------------------------------------------------------------------


@dataclass
class _Pass:
    """Numbering and counts shared by every field of one redaction."""

    username: str
    hostname: str
    keep_basename: bool
    counts: dict[str, int] = field(default_factory=dict)
    rendered: dict[tuple[str, str], str] = field(default_factory=dict)
    highest: dict[str, int] = field(default_factory=dict)

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def numbered(self, kind: str, value: str, suffix: str = "") -> str:
        """Placeholder for *value*, allocating a number on first sight."""
        key = (kind, value)
        already = self.rendered.get(key)
        if already is not None:
            return already
        number = self.highest.get(kind, 0) + 1
        self.highest[kind] = number
        placeholder = f"<{kind}_{number}{suffix}>"
        self.rendered[key] = placeholder
        return placeholder

    def seed(self, text: str) -> None:
        """Continue numbering past placeholders *text* already carries.

        Text that has been redacted before keeps its numbers, and anything
        new found in this pass is numbered after them instead of colliding.
        """
        for match in _NUMBERED_RE.finditer(text):
            kind = match.group("kind")
            number = int(match.group("number"))
            if number > self.highest.get(kind, 0):
                self.highest[kind] = number


def _placeholder_spans(text: str) -> tuple[list[int], list[int]]:
    """Start and end offsets of every placeholder in *text*, in order."""
    starts: list[int] = []
    ends: list[int] = []
    for match in _PLACEHOLDER_RE.finditer(text):
        starts.append(match.start())
        ends.append(match.end())
    return starts, ends


def _inside(spans: tuple[list[int], list[int]], match: re.Match[str]) -> bool:
    """Whether *match* falls wholly inside one of *spans*."""
    starts, ends = spans
    index = bisect_right(starts, match.start()) - 1
    return index >= 0 and match.end() <= ends[index]


# ---------------------------------------------------------------------------
# Rule 1 — s0ma keys and tokens
# ---------------------------------------------------------------------------

_RULE1_RE = re.compile(r"s0ma_test_[A-Za-z0-9_-]+|s0ma_fb_[A-Za-z0-9_-]+")


def _rule1_s0ma_keys(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        state.count(SECRETS)
        return SECRET_PLACEHOLDER

    return _RULE1_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 2 — known secret formats
#
# One alternation, longest/most-specific first, so a JWT inside a PEM block
# is consumed by the block rather than matched separately.
# ---------------------------------------------------------------------------

_RULE2_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*KEY-----(?:[\s\S]*?-----END [A-Z0-9 ]*KEY-----)?"
    rf"|Bearer\s+{_NOT_PLACEHOLDER}\S{{16,}}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|ghp_[A-Za-z0-9]{36,}"
    r"|github_pat_\w+"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]+"
)


def _rule2_known_formats(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        state.count(SECRETS)
        return SECRET_PLACEHOLDER

    return _RULE2_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 3 — env-var secret assignments (name kept, value removed)
#
# The contract's regex verbatim as re-frozen in revision r5, plus the
# placeholder guard that keeps the rule off its own output. The prefix before
# the keyword is OPTIONAL: r1's leading ``[A-Z]`` consumed the keyword's own
# first letter, so a variable named exactly the keyword (``PASSWORD=hunter2``,
# ``TOKEN=abc``, ``KEY=abc``) slipped through every rule, entropy included.
# ---------------------------------------------------------------------------

_RULE3_RE = re.compile(
    r"(?P<name>\b(?:[A-Z][A-Z0-9_]*)?(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*)"
    rf"(?P<sep>\s*=\s*)(?P<value>{_NOT_PLACEHOLDER}\S+)"
)


def _rule3_env_assignments(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        state.count(SECRETS)
        return f"{match.group('name')}{match.group('sep')}{SECRET_PLACEHOLDER}"

    return _RULE3_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 4 — emails
#
# Unicode-aware on both sides (``\w`` covers non-ASCII letters), so
# plus-addressing and internationalized domains are caught, not leaked.
# ---------------------------------------------------------------------------

_RULE4_RE = re.compile(r"(?<![\w.%+@-])[\w.%+-]+@[\w-]+(?:\.[\w-]+)+")


def _rule4_emails(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        value = match.group(0)
        # A one-character last label is a typo or a version fragment, not a
        # top-level domain. Digits are allowed: user@192.168.1.10 is an
        # address worth removing.
        if len(value.rsplit(".", 1)[-1]) < 2:
            return value
        state.count(EMAILS)
        return state.numbered("EMAIL", value)

    return _RULE4_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 5 — URLs and git remotes
# ---------------------------------------------------------------------------

# A URL is one token, and rule 4 may already have removed part of it — the
# host half of ``ssh://git@example.com/org/repo.git`` is email-shaped. So the
# body reads a placeholder as a single atom: the URL still collapses whole
# instead of leaving ``ssh://`` and a repository path behind. Angle brackets
# that are *not* a placeholder still end the match, so ``<https://x.dev/a>``
# keeps its brackets.
_URL_BODY = rf"(?:{PLACEHOLDER_PATTERN}|[^\s<>\"'`])+"

_RULE5_RE = re.compile(
    rf"\b(?:https?|ssh|ftps?|file|git)://{_URL_BODY}"
    rf"|\bgit@[\w.-]+:{_URL_BODY}"
)

#: Punctuation a URL match may have swallowed from the surrounding sentence.
_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _rule5_urls(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        value = match.group(0)
        core = value.rstrip(_TRAILING_PUNCTUATION)
        if not core:
            return value
        state.count(URLS)
        return state.numbered("URL", core) + value[len(core) :]

    return _RULE5_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 6 — absolute paths
#
# POSIX matching is scoped to the roots §7 enumerates; the Windows drive and
# UNC forms are general, as §7 writes them. See the module docstring.
# ---------------------------------------------------------------------------

#: The POSIX absolute-path roots contract §7 enumerates. Widening this list
#: changes the profile and needs a §13 re-freeze.
POSIX_PATH_ROOTS: tuple[str, ...] = ("Users", "home", "private")

_POSIX_SEGMENT = r"[^\s/\\<>\"'`:;,()\[\]{}|*?]"
_WINDOWS_SEGMENT = r"[^\s/\\<>\"'`;,()\[\]{}|*?]"
_POSIX_ROOTS = "|".join(POSIX_PATH_ROOTS)

_RULE6_RE = re.compile(
    # Windows UNC: \\server\share\...
    rf"\\\\{_WINDOWS_SEGMENT}+(?:\\{_WINDOWS_SEGMENT}+)+\\?"
    # Windows drive: C:\dir\file
    rf"|\b[A-Za-z]:\\{_WINDOWS_SEGMENT}+(?:\\{_WINDOWS_SEGMENT}+)*\\?"
    # POSIX, under the roots §7 enumerates
    rf"|(?<![\w./])/(?:{_POSIX_ROOTS})/{_POSIX_SEGMENT}+"
    rf"(?:/{_POSIX_SEGMENT}+)*/?"
)


def _basename_of(path: str) -> str:
    """Final segment of *path*, whichever separator style it uses."""
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1]


def _keeps_basename(base: str, state: _Pass) -> bool:
    """Whether *base* is load-bearing and safe to show.

    Safe means "redacting it changes nothing": a basename that is itself a
    secret, a host id, or the person's username can never survive into a
    ``<PATH_n:basename>`` placeholder.
    """
    if not _SAFE_BASENAME_RE.fullmatch(base) or "." not in base:
        return False
    probe = _Pass(username=state.username, hostname=state.hostname, keep_basename=False)
    return _apply_rules(base, probe) == base


def _rule6_paths(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        value = match.group(0)
        core = value.rstrip(_TRAILING_PUNCTUATION)
        if not core:
            return value
        suffix = ""
        if state.keep_basename:
            base = _basename_of(core)
            if _keeps_basename(base, state):
                suffix = f":{base}"
        state.count(PATHS)
        return state.numbered("PATH", core, suffix) + value[len(core) :]

    return _RULE6_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 7 — the current username outside a path
#
# Bounded like rule 9: a login name of one or two characters is far more
# likely to be an English word than a leak, so it is left alone.
# ---------------------------------------------------------------------------

USERNAME_MIN_CHARS = 3


def _rule7_username(text: str, state: _Pass) -> str:
    name = state.username
    if len(name) < USERNAME_MIN_CHARS:
        return text
    pattern = re.compile(rf"(?<![\w.-]){re.escape(name)}(?![\w-])")
    spans = _placeholder_spans(text)

    def swap(match: re.Match[str]) -> str:
        if _inside(spans, match):
            return match.group(0)
        state.count(USERNAMES)
        return USER_PLACEHOLDER

    return pattern.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 8 — hardware and host identifiers
# ---------------------------------------------------------------------------

HOSTNAME_MIN_CHARS = 3

_UUID = r"(?<![\w-])[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}(?![\w-])"
_MAC = r"(?<![\w:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:-])"
_RULE8_RE = re.compile(f"{_UUID}|{_MAC}")


def _hostname_pattern(hostname: str) -> re.Pattern[str] | None:
    """Pattern matching the local hostname and its short form, or ``None``."""
    names = {hostname, hostname.split(".", 1)[0]}
    tokens = sorted(
        (name for name in names if len(name) >= HOSTNAME_MIN_CHARS),
        key=len,
        reverse=True,
    )
    if not tokens:
        return None
    joined = "|".join(re.escape(token) for token in tokens)
    return re.compile(rf"(?<![\w.-])(?:{joined})(?![\w-])", re.IGNORECASE)


def _swap_host_ids(text: str, pattern: re.Pattern[str], state: _Pass) -> str:
    spans = _placeholder_spans(text)

    def swap(match: re.Match[str]) -> str:
        if _inside(spans, match):
            return match.group(0)
        state.count(HOST_IDS)
        return state.numbered("HOST_ID", match.group(0))

    return pattern.sub(swap, text)


def _rule8_host_ids(text: str, state: _Pass) -> str:
    text = _swap_host_ids(text, _RULE8_RE, state)
    pattern = _hostname_pattern(state.hostname) if state.hostname else None
    if pattern is None:
        return text
    return _swap_host_ids(text, pattern, state)


# ---------------------------------------------------------------------------
# Rule 9 — high-entropy strings
# ---------------------------------------------------------------------------

_RULE9_RE = re.compile(rf"[A-Za-z0-9+/=_-]{{{ENTROPY_MIN_CHARS},}}")


def _rule9_high_entropy(text: str, state: _Pass) -> str:
    spans = _placeholder_spans(text)

    def swap(match: re.Match[str]) -> str:
        value = match.group(0)
        if _inside(spans, match) or shannon_entropy(value) < ENTROPY_MIN_BITS:
            return value
        state.count(SECRETS)
        return SECRET_PLACEHOLDER

    return _RULE9_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# Rule 10 — stack-trace frames
#
# Runs last, so the path inside a frame is already a ``<PATH_n>`` when the
# frame collapses over it. Both are counted: both were removed.
# ---------------------------------------------------------------------------

_RULE10_RE = re.compile(
    r"File \"[^\"\n]*\", line \d+(?:, in \S+)?"
    r"|\bat +(?:[^\s()\n]+ +)?\([^()\n]*:\d+:\d+\)"
    r"|\bat +[^\s()\n]+:\d+:\d+"
)


def _rule10_trace_frames(text: str, state: _Pass) -> str:
    def swap(match: re.Match[str]) -> str:
        state.count(TRACE_FRAMES)
        return TRACE_PLACEHOLDER

    return _RULE10_RE.sub(swap, text)


# ---------------------------------------------------------------------------
# The profile: ten rules, in the frozen order
# ---------------------------------------------------------------------------

_RULES: tuple[Callable[[str, _Pass], str], ...] = (
    _rule1_s0ma_keys,
    _rule2_known_formats,
    _rule3_env_assignments,
    _rule4_emails,
    _rule5_urls,
    _rule6_paths,
    _rule7_username,
    _rule8_host_ids,
    _rule9_high_entropy,
    _rule10_trace_frames,
)


def _apply_rules(text: str, state: _Pass) -> str:
    for rule in _RULES:
        text = rule(text, state)
    return text


def _new_pass(
    username: str | None, hostname: str | None, keep_basename: bool
) -> _Pass:
    return _Pass(
        username=local_username() if username is None else username,
        hostname=local_hostname() if hostname is None else hostname,
        keep_basename=keep_basename,
    )


def redact(
    text: str,
    *,
    username: str | None = None,
    hostname: str | None = None,
    keep_basename: bool = False,
) -> tuple[str, dict[str, int]]:
    """Redact one piece of free text; return the text and what was removed.

    The counts map is keyed by placeholder type (:data:`COUNT_KEYS`) and
    counts occurrences removed, omitting types that removed nothing — the
    shape ``privacy.redacted`` expects.

    ``username`` and ``hostname`` default to this machine's (rules 7 and 8);
    pass ``""`` to disable either, or a literal value for a deterministic
    result. ``keep_basename`` opts into the ``<PATH_n:basename>`` form of
    rule 6 for paths whose file name is load-bearing; it is off by default,
    because §7 permits the basename rather than requiring it.

    Redacting redacted text is a fixed point, with empty counts.
    """
    state = _new_pass(username, hostname, keep_basename)
    state.seed(text)
    return _apply_rules(text, state), dict(sorted(state.counts.items()))


def redact_envelope(
    envelope: FeedbackEnvelope,
    *,
    username: str | None = None,
    hostname: str | None = None,
    keep_basename: bool = False,
) -> tuple[FeedbackEnvelope, dict[str, int]]:
    """Redact every free-text field of *envelope* in one numbered pass.

    ``summary``, ``expected``, ``actual``, ``details`` and each
    ``reproduction`` step share one numbering series walked in contract §3.1
    field order, so the second distinct path anywhere in the report is
    ``<PATH_2>`` wherever it appears, and one value keeps one placeholder
    across fields.

    Returns the redacted envelope and its ``privacy.redacted`` map. The map
    is also written into the returned envelope's privacy block, merged over
    any counts it already carried, so a redacted envelope can be redacted
    again without double-counting or drift.
    """
    state = _new_pass(username, hostname, keep_basename)
    for value in _free_text(envelope):
        state.seed(value)

    def clean(value: str | None) -> str | None:
        return None if value is None else _apply_rules(value, state)

    summary = _apply_rules(envelope.summary, state)
    expected = clean(envelope.expected)
    actual = clean(envelope.actual)
    details = clean(envelope.details)
    reproduction = tuple(_apply_rules(step, state) for step in envelope.reproduction)

    privacy = envelope.privacy if envelope.privacy is not None else FeedbackPrivacy()
    merged = dict(privacy.redacted)
    for key, removed in state.counts.items():
        merged[key] = merged.get(key, 0) + removed
    counts = dict(sorted(merged.items()))

    return (
        replace(
            envelope,
            summary=summary,
            expected=expected,
            actual=actual,
            details=details,
            reproduction=reproduction,
            privacy=replace(privacy, redacted=counts),
        ),
        counts,
    )


def _free_text(envelope: FeedbackEnvelope) -> Sequence[str]:
    """Every free-text value of *envelope*, in contract §3.1 field order."""
    values = [envelope.summary]
    values.extend(
        value
        for value in (envelope.expected, envelope.actual, envelope.details)
        if value is not None
    )
    values.extend(envelope.reproduction)
    return values
