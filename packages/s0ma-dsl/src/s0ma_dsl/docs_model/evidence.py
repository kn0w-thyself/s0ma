"""Channel-aware evidence: transcript fixtures, and the replay that checks them.

Milestone E2 of the docs-function plan (internal) §10. E1 gave a journey an
``evidence`` field and gave ``check_journeys`` an
:data:`~s0ma_dsl.docs_model.validate.EvidenceResolver` seam whose *presence*
is the arming of ``DOC_JOURNEY_UNTESTED``. This module is what lands behind
that seam: a fixture format an author writes, a replay that runs it for
real, and the resolver the documentation application wires in.

**What a transcript fixture is.** One JSON file per fixture under
:data:`EVIDENCE_DIR`, declaring the journey it evidences, the channel it
speaks, how a throwaway project is prepared, the ordered things a reader
does, and what each of them must produce. Architecture §8.4 allows exactly
this and words the boundary it is allowed against: a transcript fixture is
"a runner extension, not permission to paste unverified shell sessions into
prose". So nothing here is an expected output somebody typed from memory —
every line a fixture claims is compared against a line a real run produced,
in a temporary directory, under the house's subprocess discipline.

**Two channels, one shape.** A ``cli`` fixture runs commands as argv lists;
an ``mcp`` fixture calls tools on the real authoring server, created
in-process, on the same kind of scaffolded project. Both read the same way,
carry the same placeholder vocabulary and are compared by the same
line-cursor algorithm, because an author who has written one should not have
to learn a second format to write the other.

**The E2 T3 split: resolution in the build, execution in the suite.**

* :meth:`EvidenceLibrary.resolver` — pure file reading, no subprocess, no
  clock, no socket. This is what :func:`~s0ma_dsl.docs_model.application.build`
  wires in, and it answers the only question an offline build can honestly
  answer: does this journey name evidence this repository actually holds,
  well-formed and claiming this journey back. SDA-INV-8 makes that the
  whole of what the build may do — a documentation build that shelled out
  to a toolchain would stop being deterministic and offline the moment it
  ran, and ``s0ma docs check`` would start depending on what is installed
  rather than on what is written;
* :func:`verify` — the execution half, which really does run things and
  therefore lives in the test suite (``test_docs_evidence.py``).

The two halves are held together by a test that pins the resolved set equal
to the executed set, so a fixture cannot be resolved by the build and run by
nobody. What the split cannot catch, said plainly: a build on a machine
where the suite has never run still resolves its evidence. Closing that is
CI's job — the same run that composes the documentation runs the suite —
and it is why the resolution half reports *resolution* in its message
rather than claiming a run it did not watch.

**Determinism.** A replay produces a normalized transcript: every machine
fact is replaced by a placeholder from a closed vocabulary
(:data:`PLACEHOLDERS`), line endings are line feeds, and trailing whitespace
is stripped. Two replays of one fixture are byte-equal, which is the
property the suite asserts and the reason the format has no free-form regex
in it unless a written reason rides the entry.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import id_form, normalize_id, validate_id
from s0ma_dsl.docs_model.providers import DocsProviderError, Finding, sort_findings
from s0ma_dsl.docs_model.providers_concepts import (
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
)
from s0ma_dsl.docs_model.validate import DOC_GATE_VACUOUS, DOC_JOURNEY_UNRESOLVED

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from s0ma_dsl.docs_model.records import DocsBundle, JourneyRecord

__all__ = [
    "CHANNELS",
    "CHANNEL_CLI",
    "CHANNEL_MCP",
    "DOC_EXAMPLE_FAILED",
    "EVIDENCE_DIR",
    "EVIDENCE_SCHEMA",
    "MATCHES",
    "PLACEHOLDERS",
    "PROGRAMS",
    "REPLAY_TIMEOUT_SECONDS",
    "CallStep",
    "CommandStep",
    "Divergence",
    "DocsEvidenceError",
    "EvidenceLibrary",
    "EvidenceRecord",
    "Expectation",
    "FieldExpectation",
    "Observed",
    "Replay",
    "Scaffold",
    "Verification",
    "WriteStep",
    "check_evidence_voice",
    "compare",
    "normalize",
    "passing",
    "replay",
    "verify",
    "verify_all",
]


class DocsEvidenceError(DocsProviderError):
    """A transcript fixture is not the shape this loader reads.

    A refusal rather than a finding, for the line C5a drew and every
    authored-source loader since has kept: a file that does not satisfy
    its own schema cannot be partially believed. Something being *wrong*
    with a fixture that loaded — its replay diverging, its ledger
    disagreeing with the journey — is a
    :class:`~s0ma_dsl.docs_model.providers.Finding` instead, collected so
    an author sees every one of them in one run.
    """


# ---------------------------------------------------------------------------
# Diagnostic names
# ---------------------------------------------------------------------------

#: A referenced executable example or transcript fixture fails
#: (architecture plan §11). **Armed here**: E1 could name the seam and had
#: nothing that could run, and this is the runner. Not a minted code — §11
#: froze this name for exactly this failure — so it takes no row in
#: :data:`~s0ma_dsl.docs_model.validate.MINTED_CODES`; what it takes is a
#: fixture in the negative battery, which the completeness audit demands of
#: every code the ``docs_model`` source tree names.
DOC_EXAMPLE_FAILED = "DOC_EXAMPLE_FAILED"


# ---------------------------------------------------------------------------
# Where evidence lives, and what it may say
# ---------------------------------------------------------------------------

#: The authored file's own schema. Not the model's, for the reason C5a
#: gave and E1 repeated: a fixture is an *input* to the documentation
#: model rather than a serialization of it, and one version string over
#: both would make a change to either look like a change to both.
EVIDENCE_SCHEMA = "s0ma-docs-evidence@1"

#: Where transcript fixtures live, repository-relative (ADR-012 §1). One
#: file per fixture, and the file's stem is the last segment of its id —
#: so a reader holding ``example:transcript/first-project`` opens
#: ``first-project.json`` and a file renamed away from its record is
#: refused rather than silently orphaned.
EVIDENCE_DIR = "docs/s0ma_src/evidence"

#: The two channels a fixture may speak. ``cli`` replays argv lists
#: against the installed command line; ``mcp`` calls tools on the real
#: authoring server. There is deliberately no third: a channel is a way a
#: reader reaches the product, and one that cannot be replayed offline
#: under a timeout is one this format refuses rather than fakes.
CHANNEL_CLI = "cli"
CHANNEL_MCP = "mcp"
CHANNELS: tuple[str, ...] = (CHANNEL_CLI, CHANNEL_MCP)

#: The only programs a transcript may run, mapped to how this process
#: finds them. **This is the no-network guard with teeth.** A fixture
#: cannot name ``curl``, cannot name a shell, and cannot name a script it
#: wrote a moment ago: the closed set is the whole of what a replay is
#: able to execute, which is a stronger promise than any environment
#: variable, and it is why the command field is an argv list rather than a
#: shell string. A shell string would have to be split by something, and
#: whatever split it would eventually be asked to understand a pipe.
PROGRAMS: tuple[str, ...] = ("s0ma",)

#: How long any one command may take before the replay kills it and calls
#: the fixture failed. Twice the house default
#: (``s0ma.examples.timeout.DEFAULT_TIMEOUT_SECONDS``) because a cold
#: Windows CI filesystem scaffolding a project is the slowest thing a
#: fixture legitimately does, and a fixture that needs longer than this is
#: a fixture doing too much to be evidence of one path.
REPLAY_TIMEOUT_SECONDS = 60.0


# ---------------------------------------------------------------------------
# The placeholder vocabulary
# ---------------------------------------------------------------------------

#: The temporary root a replay works in.
TMP = "{tmp}"

#: The scaffolded project inside it — the directory the transcript's
#: commands run in.
PROJECT = "{project}"

#: The version of the toolchain that ran.
VERSION = "{version}"

#: A measured duration, elided.
DURATION = "{duration}"

#: Every placeholder an author may write, with what it stands for. Closed,
#: and checked at load time in both directions: a fixture naming
#: ``{tmpdir}`` is refused by name rather than quietly never matching,
#: which is the failure mode a free-form expected-output format has.
#:
#: Two of them travel *inbound* as well — an MCP tool takes the project
#: root as an argument, so ``{project}`` has to be substituted on the way
#: in and recognised on the way out. The other two are outbound only:
#: nothing a reader types contains the toolchain version, and nothing
#: types a duration at all.
PLACEHOLDERS: Mapping[str, str] = {
    TMP: "the throwaway directory this replay ran in",
    PROJECT: "the scaffolded project inside it",
    VERSION: "the version of the toolchain that ran",
    DURATION: "a measured duration, elided because it is never the same twice",
}

#: The placeholders substituted into argv and tool arguments before a step
#: runs. Both are paths, and both are paths only this process knows.
INBOUND: tuple[str, ...] = (PROJECT, TMP)

#: What an expectation may say about a stream. Four, and the fourth is
#: fenced: ``regex`` is the escape hatch for a line no literal can
#: describe, and it is refused unless the entry carries a written
#: ``reason``. The default is a literal because a literal is reviewable —
#: a person reading a diff can see what the product said, which is the
#: whole point of committing a transcript.
MATCHES: tuple[str, ...] = ("absent", "contains", "line", "regex")

#: The JSON keys whose numeric value is a measured duration. Closed and
#: short on purpose: a normalizer that elided every number ending in
#: ``ms`` would eat real content, and a fixture whose output carries a
#: duration under some other name is caught by the two-replay gate rather
#: than silently normalized.
DURATION_KEYS: tuple[str, ...] = ("duration", "duration_ms", "elapsed", "elapsed_ms")

_DURATION = re.compile(
    r'("(?:' + "|".join(DURATION_KEYS) + r')"\s*:\s*)-?\d+(?:\.\d+)?'
)

#: A ``{word}`` token, for checking an authored expectation against the
#: vocabulary above. Deliberately narrow: JSON output is full of braces,
#: and ``{"ok": true}`` must not read as a placeholder nobody declared.
_TOKEN = re.compile(r"\{[a-z][a-z-]*\}")


# ---------------------------------------------------------------------------
# What an author writes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expectation:
    """One thing a stream must say, and how the runner is to look for it.

    ``match`` is one of :data:`MATCHES`. ``text`` is a literal for the
    three literal kinds and a pattern for ``regex``. ``reason`` is empty
    except on a ``regex``, where it is required and says why no literal
    would do — a sentence a reviewer reads, not a formality.

    Expectations over one stream are an **ordered subsequence** of its
    lines: each is searched for at or after the line the previous one
    matched. That is what makes a transcript a transcript rather than a
    bag of substrings, and it is what lets a failure say which line the
    search had reached.
    """

    match: str
    text: str
    reason: str = ""


@dataclass(frozen=True)
class FieldExpectation:
    """One value inside a structured result, addressed by a dotted path.

    ``path`` walks objects by key and lists by index — ``build.status``,
    ``modules.0.name``. ``equals`` is the value it must hold, compared
    after the same normalization the text gets, so a path may be written
    as ``{project}/src/app_map.s0ma`` and mean it.
    """

    path: str
    equals: Any


@dataclass(frozen=True)
class CommandStep:
    """One command a reader types, and what it must produce."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: tuple[Expectation, ...]
    stderr: tuple[Expectation, ...]


@dataclass(frozen=True)
class CallStep:
    """One tool call an agent makes, and what must come back.

    ``arguments`` is held as sorted pairs rather than a mapping so the
    step is hashable and orders one way — the same reason every other
    collection in this model is a tuple.
    """

    tool: str
    arguments: tuple[tuple[str, Any], ...]
    text: tuple[Expectation, ...]
    fields: tuple[FieldExpectation, ...]


@dataclass(frozen=True)
class WriteStep:
    """A file the reader writes between two commands.

    A walkthrough that never edits anything can only evidence a path
    nobody walks: "check, change what it told you about, check again" is
    the loop, and the change is a step of it. It runs no program and has
    no output, so it has nothing to expect — it appears in the transcript
    as the edit it is, and the command after it is what says whether the
    edit did what the guide claims.
    """

    path: str
    text: str


#: One thing a reader does. Three kinds, and the union is the type the
#: replay walks.
Step = CommandStep | CallStep | WriteStep


@dataclass(frozen=True)
class Scaffold:
    """How the throwaway project is prepared before step one.

    Two kinds, because two are what the five canonical journeys need:

    * ``new-project`` runs the product's own initializer — the honest
      preparation for any journey whose reader starts by making a project;
    * ``authored-tree`` writes a named set of files, for a journey that
      starts from a tree that is deliberately not what the initializer
      makes (a drifted project, a half-adopted one).

    ``workdir`` is where the transcript's commands then run, relative to
    the temporary root.
    """

    kind: str
    argv: tuple[str, ...]
    files: tuple[tuple[str, str], ...]
    workdir: str


@dataclass(frozen=True)
class EvidenceRecord:
    """One transcript fixture: what it evidences, and what it does.

    ``covers`` and ``not_covered`` are the honesty ledger. Between them
    they must name exactly the surfaces the journey's steps name — the
    gate is :meth:`EvidenceLibrary.findings`, which is the only place that
    can ask, because only the composition knows what the journey's steps
    are. A fixture that exercises three of a journey's four steps says so,
    by id, with a reason for the fourth; it does not quietly evidence a
    path and let a reader assume the rest.
    """

    id: str
    journey: str
    channel: str
    intent: str
    scaffold: Scaffold
    steps: tuple[Step, ...]
    covers: tuple[str, ...]
    not_covered: tuple[tuple[str, str], ...]
    source: str


# ---------------------------------------------------------------------------
# What a replay produces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Observed:
    """What one step actually did, normalized.

    ``streams`` is name → normalized text, in a fixed order.
    ``structured`` is the machine-readable half of a tool result, with
    every string in it normalized, or ``None`` for a channel that has
    none.
    """

    label: str
    streams: tuple[tuple[str, str], ...]
    exit_code: int | None
    structured: Any
    timed_out: bool

    def stream(self, name: str) -> str:
        """The normalized text of one stream, empty when there is none."""
        for held, text in self.streams:
            if held == name:
                return text
        return ""


@dataclass(frozen=True)
class Replay:
    """One run of one fixture, and the transcript it produced."""

    record_id: str
    observed: tuple[Observed, ...]
    transcript: str


@dataclass(frozen=True)
class Divergence:
    """The first place a replay stopped agreeing with the fixture.

    Located the way a compiler locates: which step, which stream, which
    expectation, and the line the search had reached when it ran out of
    output. ``line`` is one-based over the normalized stream, and zero
    where the stream has no lines to count (an exit code, a structured
    field).
    """

    step: int
    stream: str
    expectation: int
    line: int
    detail: str

    def rendered(self) -> str:
        """The one-line form, naming everything needed to find it."""
        return (
            f"step {self.step + 1}, {self.stream}, expectation "
            f"{self.expectation + 1}, at line {self.line}: {self.detail}"
        )


@dataclass(frozen=True)
class Verification:
    """Whether one fixture still describes the product, and where it does not."""

    record_id: str
    ok: bool
    divergence: Divergence | None
    findings: tuple[Finding, ...]
    replay: Replay | None


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _path_forms(path: Path) -> tuple[str, ...]:
    """Every spelling of ``path`` a subprocess might hand back.

    Three sources and three spellings, because one run produces more than
    one of them: macOS resolves ``/var/folders/...`` to
    ``/private/var/folders/...`` for some readings and not others (the
    authoring server's own results carry both), and a Windows path
    reaches a JSON result with its separators doubled.
    """
    seen: set[str] = set()
    for base in (str(path), str(path.resolve()), os.path.realpath(str(path))):
        seen.add(base)
        seen.add(base.replace("\\", "/"))
        seen.add(base.replace("\\", "\\\\"))
    return tuple(sorted(seen))


def _needles(tmp: Path, project: Path) -> tuple[tuple[str, str], ...]:
    """Machine paths and the tokens that replace them, longest first.

    Longest first matters and is not a micro-optimization: the project
    directory lives *inside* the temporary root, so replacing the shorter
    one first would leave ``{tmp}/demo`` where ``{project}`` belongs and
    the two would drift apart the day a fixture moved its workdir.
    """
    pairs: set[tuple[str, str]] = set()
    for path, token in ((project, PROJECT), (tmp, TMP)):
        for form in _path_forms(path):
            pairs.add((form, token))
    return tuple(sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])))


def normalize(
    text: str,
    *,
    tmp: Path,
    project: Path,
    version: str,
) -> str:
    """One run's output with every machine fact replaced by a placeholder.

    In order: line endings become line feeds, the two paths become their
    tokens (longest first), the toolchain version becomes ``{version}``,
    a measured duration becomes ``{duration}``, and every line loses its
    trailing whitespace. Nothing here is authorable — the same four
    normalizers run over every fixture on every channel, so two fixtures
    cannot disagree about what a machine fact is.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for needle, token in _needles(tmp, project):
        normalized = normalized.replace(needle, token)
    if version:
        normalized = normalized.replace(version, VERSION)
    normalized = _DURATION.sub(r"\g<1>" + DURATION, normalized)
    return "\n".join(line.rstrip() for line in normalized.split("\n"))


def _normalize_value(value: Any, *, tmp: Path, project: Path, version: str) -> Any:
    """The same normalization, over every string inside a structured result."""
    if isinstance(value, str):
        return normalize(value, tmp=tmp, project=project, version=version)
    if isinstance(value, dict):
        return {
            key: _normalize_value(held, tmp=tmp, project=project, version=version)
            for key, held in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_value(held, tmp=tmp, project=project, version=version)
            for held in value
        ]
    return value


def _substitute(value: Any, *, tmp: Path, project: Path) -> Any:
    """The inbound half: ``{project}`` and ``{tmp}`` become real paths.

    Recursive, because a tool argument may be a list or an object, and a
    path inside one is the same path.
    """
    if isinstance(value, str):
        real = {PROJECT: str(project), TMP: str(tmp)}
        for token in INBOUND:
            value = value.replace(token, real[token])
        return value
    if isinstance(value, dict):
        return {key: _substitute(held, tmp=tmp, project=project) for key, held in value.items()}
    if isinstance(value, list):
        return [_substitute(held, tmp=tmp, project=project) for held in value]
    return value


# ---------------------------------------------------------------------------
# Reading a fixture
# ---------------------------------------------------------------------------


def _named(value: Any) -> str:
    """The kind of thing ``value`` is, in the words a JSON author uses."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a true/false value"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, str):
        return "text"
    return "a number"


def _object(value: Any, where: str) -> dict[str, Any]:
    """``value`` as a JSON object, refusing anything else by name."""
    if not isinstance(value, dict):
        raise DocsEvidenceError(f"{where}: expected an object, got {_named(value)}")
    return value


def _array(value: Any, where: str) -> list[Any]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise DocsEvidenceError(f"{where}: expected a list, got {_named(value)}")
    return value


def _text(value: Any, where: str) -> str:
    """``value`` as a non-empty string, refusing anything else by name."""
    if not isinstance(value, str):
        raise DocsEvidenceError(f"{where}: expected text, got {_named(value)}")
    if not value.strip():
        raise DocsEvidenceError(
            f"{where}: is empty. An empty field is not the same as an absent "
            f"one, and this model has nowhere to put an unwritten fact."
        )
    return value


def _exactly(raw: Mapping[str, Any], expected: Sequence[str], where: str) -> None:
    """Refuse an object that does not carry exactly the expected keys."""
    unknown = sorted(set(raw) - set(expected))
    missing = sorted(set(expected) - set(raw))
    if unknown or missing:
        raise DocsEvidenceError(
            f"{where}: does not match the {EVIDENCE_SCHEMA} shape "
            f"(unexpected: {unknown}, absent: {missing})"
        )


def _tokens(text: str, where: str) -> None:
    """Every ``{word}`` an author wrote is one this vocabulary knows."""
    for found in _TOKEN.findall(text):
        if found not in PLACEHOLDERS:
            raise DocsEvidenceError(
                f"{where}: names the placeholder {found}, and the vocabulary "
                f"is {sorted(PLACEHOLDERS)}. A placeholder nobody substitutes "
                f"never matches, and an expectation that never matches is how "
                f"a transcript quietly stops checking anything."
            )


_EXPECTATION_KEYS = ("match", "text")
_REGEX_KEYS = ("match", "reason", "text")


def _read_expectation(entry: Any, where: str) -> Expectation:
    """One expectation over one stream, with the regex fence."""
    item = _object(entry, where)
    match = _text(item.get("match"), f"{where}/match")
    if match not in MATCHES:
        raise DocsEvidenceError(
            f"{where}/match: {match!r} is not one of {list(MATCHES)}"
        )
    _exactly(item, _REGEX_KEYS if match == "regex" else _EXPECTATION_KEYS, where)
    text = _text(item["text"], f"{where}/text")
    _tokens(text, f"{where}/text")
    if match != "regex":
        return Expectation(match=match, text=text, reason="")
    reason = _text(item["reason"], f"{where}/reason")
    try:
        re.compile(text)
    except re.error as broken:
        raise DocsEvidenceError(
            f"{where}/text: {text!r} is not a readable regular expression "
            f"({broken})"
        ) from broken
    return Expectation(match=match, text=text, reason=reason)


def _read_expectations(raw: Any, where: str) -> tuple[Expectation, ...]:
    """The ordered expectations over one stream."""
    return tuple(
        _read_expectation(entry, f"{where}/{index}")
        for index, entry in enumerate(_array(raw, where))
    )


_FIELD_KEYS = ("equals", "path")


def _read_field(entry: Any, where: str) -> FieldExpectation:
    """One expectation over one value of a structured result."""
    item = _object(entry, where)
    _exactly(item, _FIELD_KEYS, where)
    path = _text(item["path"], f"{where}/path")
    if path.startswith(".") or path.endswith(".") or ".." in path:
        raise DocsEvidenceError(
            f"{where}/path: {path!r} is not a path through a result. Write "
            f"the keys separated by dots, with a number for a position in a "
            f"list — build.status, modules.0.name."
        )
    equals = item["equals"]
    if isinstance(equals, str):
        _tokens(equals, f"{where}/equals")
    return FieldExpectation(path=path, equals=equals)


_COMMAND_KEYS = ("argv", "exit_code", "stderr", "stdout")
_CALL_KEYS = ("arguments", "fields", "text", "tool")
_WRITE_KEYS = ("path", "text")


def _read_argv(raw: Any, where: str) -> tuple[str, ...]:
    """One command as argv, never as a shell string."""
    entries = _array(raw, where)
    if not entries:
        raise DocsEvidenceError(f"{where}: is empty; a command needs a program")
    argv = tuple(_text(entry, f"{where}/{index}") for index, entry in enumerate(entries))
    if argv[0] not in PROGRAMS:
        raise DocsEvidenceError(
            f"{where}/0: {argv[0]!r} is not a program a transcript may run. "
            f"The set is {list(PROGRAMS)} — a fixture replays this product, "
            f"and a fixture able to run anything else is a fixture able to "
            f"reach the network."
        )
    for index, part in enumerate(argv):
        _tokens(part, f"{where}/{index}")
    return argv


def _read_step(entry: Any, where: str, channel: str) -> Step:
    """One step, of the kind its keys say it is."""
    item = _object(entry, where)
    keys = set(item)
    if keys == set(_WRITE_KEYS):
        path = _relative(_text(item["path"], f"{where}/path"), f"{where}/path")
        if not isinstance(item["text"], str):
            raise DocsEvidenceError(f"{where}/text: expected text, got {_named(item['text'])}")
        return WriteStep(path=path, text=item["text"])
    if channel == CHANNEL_CLI:
        _exactly(item, _COMMAND_KEYS, where)
        exit_code = item["exit_code"]
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise DocsEvidenceError(
                f"{where}/exit_code: expected a number, got {_named(exit_code)}"
            )
        return CommandStep(
            argv=_read_argv(item["argv"], f"{where}/argv"),
            exit_code=exit_code,
            stdout=_read_expectations(item["stdout"], f"{where}/stdout"),
            stderr=_read_expectations(item["stderr"], f"{where}/stderr"),
        )
    _exactly(item, _CALL_KEYS, where)
    arguments = _object(item["arguments"], f"{where}/arguments")
    for key, value in sorted(arguments.items()):
        if isinstance(value, str):
            _tokens(value, f"{where}/arguments/{key}")
    return CallStep(
        tool=_text(item["tool"], f"{where}/tool"),
        arguments=tuple(sorted(arguments.items())),
        text=_read_expectations(item["text"], f"{where}/text"),
        fields=tuple(
            _read_field(held, f"{where}/fields/{index}")
            for index, held in enumerate(_array(item["fields"], f"{where}/fields"))
        ),
    )


def _relative(path: str, where: str) -> str:
    """A path inside the temporary tree, refusing one that leaves it."""
    if path.startswith("/") or path.startswith("\\") or ":" in path or ".." in path:
        raise DocsEvidenceError(
            f"{where}: {path!r} is not a path inside the throwaway project. "
            f"Write it relative and forward-slashed; a replay writes nowhere "
            f"but the directory it made."
        )
    return path


_SCAFFOLD_KINDS = ("authored-tree", "new-project")
_NEW_PROJECT_KEYS = ("argv", "kind", "workdir")
_AUTHORED_TREE_KEYS = ("files", "kind", "workdir")


def _read_scaffold(entry: Any, where: str) -> Scaffold:
    """How the throwaway project is prepared, of the kind it declares."""
    item = _object(entry, where)
    kind = _text(item.get("kind"), f"{where}/kind")
    if kind not in _SCAFFOLD_KINDS:
        raise DocsEvidenceError(
            f"{where}/kind: {kind!r} is not one of {list(_SCAFFOLD_KINDS)}"
        )
    workdir = item.get("workdir")
    if not isinstance(workdir, str):
        raise DocsEvidenceError(f"{where}/workdir: expected text, got {_named(workdir)}")
    if workdir not in ("", "."):
        _relative(workdir, f"{where}/workdir")
    if kind == "new-project":
        _exactly(item, _NEW_PROJECT_KEYS, where)
        return Scaffold(
            kind=kind,
            argv=_read_argv(item["argv"], f"{where}/argv"),
            files=(),
            workdir=workdir or ".",
        )
    _exactly(item, _AUTHORED_TREE_KEYS, where)
    files = _object(item["files"], f"{where}/files")
    if not files:
        raise DocsEvidenceError(
            f"{where}/files: is empty. An authored tree with no files is a "
            f"scaffold that prepares nothing."
        )
    written: list[tuple[str, str]] = []
    for name in sorted(files):
        value = files[name]
        if not isinstance(value, str):
            raise DocsEvidenceError(
                f"{where}/files/{name}: expected text, got {_named(value)}"
            )
        written.append((_relative(name, f"{where}/files/{name}"), value))
    return Scaffold(kind=kind, argv=(), files=tuple(written), workdir=workdir or ".")


_RECORD_KEYS = (
    "channel",
    "covers",
    "id",
    "intent",
    "journey",
    "not_covered",
    "scaffold",
    "steps",
)
_NOT_COVERED_KEYS = ("reason", "surface")


def _read_ledger(raw: Any, where: str) -> tuple[tuple[str, str], ...]:
    """The surfaces this transcript does not reach, each with why."""
    found: list[tuple[str, str]] = []
    for index, entry in enumerate(_array(raw, where)):
        at = f"{where}/{index}"
        item = _object(entry, at)
        _exactly(item, _NOT_COVERED_KEYS, at)
        surface = _text(item["surface"], f"{at}/surface")
        validate_id(surface)
        found.append((surface, _text(item["reason"], f"{at}/reason")))
    ids = [surface for surface, _ in found]
    if ids != sorted(ids):
        raise DocsEvidenceError(f"{where}: is not sorted by surface")
    if len(set(ids)) != len(ids):
        raise DocsEvidenceError(f"{where}: names one surface twice")
    return tuple(found)


def _read_covers(raw: Any, where: str) -> tuple[str, ...]:
    """The surfaces this transcript really exercises."""
    found = tuple(
        _text(entry, f"{where}/{index}") for index, entry in enumerate(_array(raw, where))
    )
    for surface in found:
        validate_id(surface)
    if list(found) != sorted(found):
        raise DocsEvidenceError(f"{where}: is not sorted")
    if len(set(found)) != len(found):
        raise DocsEvidenceError(f"{where}: names one surface twice")
    return found


def _read_record(entry: Any, where: str, source: str, stem: str) -> EvidenceRecord:
    """One authored fixture as a record, every reference checked in form."""
    item = _object(entry, where)
    _exactly(item, _RECORD_KEYS, where)

    identifier = _text(item["id"], f"{where}/id")
    if id_form(identifier) != "example":
        raise DocsEvidenceError(
            f"{where}/id: {identifier!r} is not an example id. A transcript "
            f"fixture is registered runnable evidence, and it takes one "
            f"colon, always."
        )
    validate_id(identifier)
    if identifier.rsplit("/", 1)[-1] != stem:
        raise DocsEvidenceError(
            f"{where}/id: the file is named {stem}.json and the record is "
            f"{identifier!r}. The file's stem is the id's last segment, so a "
            f"reader holding the id opens the file that holds it."
        )

    journey = _text(item["journey"], f"{where}/journey")
    if id_form(journey) != "journey":
        raise DocsEvidenceError(
            f"{where}/journey: {journey!r} is not a journey id. Evidence "
            f"evidences a path; the path is addressed by its slug."
        )
    validate_id(journey)

    channel = _text(item["channel"], f"{where}/channel")
    if channel not in CHANNELS:
        raise DocsEvidenceError(
            f"{where}/channel: {channel!r} is not one of {list(CHANNELS)}"
        )

    steps = tuple(
        _read_step(held, f"{where}/steps/{index}", channel)
        for index, held in enumerate(_array(item["steps"], f"{where}/steps"))
    )
    if not any(isinstance(step, CommandStep | CallStep) for step in steps):
        raise DocsEvidenceError(
            f"{where}/steps: runs nothing. A transcript that only writes "
            f"files evidences no path — something has to be asked, and "
            f"something has to answer."
        )

    covers = _read_covers(item["covers"], f"{where}/covers")
    not_covered = _read_ledger(item["not_covered"], f"{where}/not_covered")
    overlap = sorted(set(covers) & {surface for surface, _ in not_covered})
    if overlap:
        raise DocsEvidenceError(
            f"{where}: {overlap} are recorded both as covered and as not "
            f"covered. A step is one or the other."
        )
    return EvidenceRecord(
        id=identifier,
        journey=journey,
        channel=channel,
        intent=_text(item["intent"], f"{where}/intent"),
        scaffold=_read_scaffold(item["scaffold"], f"{where}/scaffold"),
        steps=steps,
        covers=covers,
        not_covered=not_covered,
        source=source,
    )


def _read_file(text: str, source: str, stem: str) -> EvidenceRecord:
    """One file as one record, refusing every shape it is not."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as broken:
        raise DocsEvidenceError(
            f"{source}: is not readable as JSON ({broken.msg} at line "
            f"{broken.lineno}, column {broken.colno})"
        ) from broken
    raw = _object(document, source)
    _exactly(raw, ("record", "schema"), source)
    schema = _text(raw["schema"], f"{source}#/schema")
    if schema != EVIDENCE_SCHEMA:
        raise DocsEvidenceError(
            f"{source}#/schema: this loader reads {EVIDENCE_SCHEMA!r}; the "
            f"file names {schema!r}"
        )
    return _read_record(raw["record"], f"{source}#/record", source, stem)


# ---------------------------------------------------------------------------
# The library, and the resolver the build wires in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceLibrary:
    """Every transcript fixture this repository holds, read once.

    Reading only. No subprocess, no clock, no socket — this is the half
    of E2 that runs inside the documentation build, and SDA-INV-8 is the
    reason it is only a reading.
    """

    records: tuple[EvidenceRecord, ...]
    relative: str = EVIDENCE_DIR

    @classmethod
    def load(cls, root: Path, *, relative: str = EVIDENCE_DIR) -> EvidenceLibrary:
        """Every fixture under ``relative``, in file-name order.

        A directory that is not there is an **empty library**, not a
        refusal: a repository that has written no evidence has written
        none, and ``DOC_JOURNEY_UNTESTED`` tells that story per journey
        far better than an exception that stops the build telling any
        story at all. A file that *is* there and does not parse is a
        refusal, because a fixture believed in part is worse than none.

        There is no duplicate-id check here, and its absence is the
        design rather than an omission: the file's stem must be the id's
        last segment, and a directory holds one file per name, so two
        files under one id is a shape nobody can write down. A second
        check for it would be a gate that can never fire.
        """
        directory = root.joinpath(*relative.split("/"))
        if not directory.is_dir():
            return cls(records=(), relative=relative)
        return cls(
            records=tuple(
                _read_file(
                    path.read_text(encoding="utf-8"), f"{relative}/{path.name}", path.stem
                )
                for path in sorted(directory.glob("*.json"))
            ),
            relative=relative,
        )

    def ids(self) -> tuple[str, ...]:
        """Every fixture id, sorted.

        Handed to the composition as external ids: a fixture is
        registered runnable evidence and lives outside the documentation
        model, exactly like a registered component, so the resolver is
        told about it rather than asked to find it.
        """
        return tuple(sorted(record.id for record in self.records))

    def by_id(self, identifier: str) -> EvidenceRecord:
        """The fixture ``identifier`` addresses, refusing one nothing answers to."""
        wanted = normalize_id(identifier)
        for record in self.records:
            if normalize_id(record.id) == wanted:
                return record
        raise DocsEvidenceError(f"this library holds nothing called {identifier!r}")

    def for_journey(self, journey_id: str) -> tuple[EvidenceRecord, ...]:
        """Every fixture claiming to evidence ``journey_id``, sorted by id."""
        wanted = normalize_id(journey_id)
        return tuple(
            sorted(
                (
                    record
                    for record in self.records
                    if normalize_id(record.journey) == wanted
                ),
                key=lambda record: record.id,
            )
        )

    def resolver(self) -> Callable[[str], tuple[str, ...]]:
        """The :data:`~s0ma_dsl.docs_model.validate.EvidenceResolver` this library is.

        Journey id in, the ids of the evidence that resolves for it out.
        **Resolves**, not *ran*: this is the T3 split, and the word is
        chosen rather than loose. What a subprocess-free build can see is
        that the named fixture exists in this tree, parses, and names this
        journey back; whether it still replays green is the suite's
        question, asked by :func:`verify` on every fixture in this
        library.

        The arming is unconditional — a resolver is always handed over —
        so ``DOC_JOURNEY_UNTESTED`` fires for a journey whose evidence is
        empty or whose evidence this tree does not hold, which are the two
        failures a build can honestly detect.
        """

        def resolve(journey_id: str) -> tuple[str, ...]:
            return tuple(record.id for record in self.for_journey(journey_id))

        return resolve

    def findings(self, bundle: DocsBundle) -> tuple[Finding, ...]:
        """What is wrong with this library, given the journeys it claims.

        Three questions, none of which a fixture can answer about itself:

        * a fixture naming a journey this build does not address is a
          citation that does not resolve (``DOC_JOURNEY_UNRESOLVED``);
        * a fixture no journey names as its evidence is a check nobody
          runs for a reason anybody can see (``DOC_GATE_VACUOUS`` — the
          same finding a side-effect allowance nothing uses gets, for the
          same reason);
        * a ledger that does not account for exactly the journey's step
          surfaces is a claim about coverage that nobody can check, and a
          journey citing the fixture at a path the fixture is not written
          at is a citation that resolves by id and misdirects a reader
          (both ``DOC_JOURNEY_UNRESOLVED``).

        **Nothing is reported when the bundle holds no journeys.** A
        composition without the journeys reading has not disproved
        anything about this library; it has left the question unasked,
        and its own floor already reports the absence. That is the same
        rule the application states for its floors and allowances: a
        claim about *these* readings, asserted over somebody else's,
        reports the absence of this repository rather than anything about
        theirs.
        """
        if not bundle.journeys:
            return ()
        journeys = {normalize_id(record.id): record for record in bundle.journeys}
        claimed: set[str] = {
            normalize_id(item.id) for record in bundle.journeys for item in record.evidence
        }
        findings: list[Finding] = []
        for record in self.records:
            journey = journeys.get(normalize_id(record.journey))
            if journey is None:
                findings.append(
                    Finding(
                        code=DOC_JOURNEY_UNRESOLVED,
                        location=record.source,
                        message=(
                            f"{record.id} evidences {record.journey}, and this "
                            f"build addresses no such journey"
                        ),
                        remediation=(
                            "Either the journey was renamed and its evidence "
                            "still names the old id, or the fixture was "
                            "written against a path nobody has authored yet. "
                            "Evidence for a journey that does not exist proves "
                            "nothing and is never run."
                        ),
                    )
                )
                continue
            if normalize_id(record.id) not in claimed:
                findings.append(
                    Finding(
                        code=DOC_GATE_VACUOUS,
                        location=record.source,
                        message=(
                            f"{record.id} evidences {journey.id} and "
                            f"{journey.id} does not name it as evidence, so "
                            f"nothing this build does depends on it passing"
                        ),
                        remediation=(
                            f"Add {record.id} to the journey's evidence, or "
                            f"delete the fixture. A transcript nobody claims "
                            f"goes stale with no one to notice, which is the "
                            f"failure the whole gate exists against."
                        ),
                    )
                )
            findings.extend(_ledger_findings(record, journey))
            findings.extend(_source_findings(record, journey))
        return sort_findings(findings)


def _source_findings(record: EvidenceRecord, journey: JourneyRecord) -> list[Finding]:
    """The journey cites the fixture at the file the fixture is written in.

    ``ExampleRef`` carries a source beside the id for the reason C1 gave
    it one — "a bare id string cannot be checked against a source file;
    this can" — and this is the check that was waiting for something to
    check against. A moved fixture whose citation stayed behind still
    resolves by id and sends a reader to a file that is not there.
    """
    return [
        Finding(
            code=DOC_JOURNEY_UNRESOLVED,
            location=record.source,
            message=(
                f"{journey.id} cites {record.id} as written in "
                f"{cited.source!r} and it is written in {record.source!r}"
            ),
            remediation=(
                "Point the citation at the file the fixture is in. The id "
                "resolving is not enough on its own: the source is what a "
                "reader opens and what a later milestone reads the fixture "
                "back from."
            ),
        )
        for cited in journey.evidence
        if normalize_id(cited.id) == normalize_id(record.id)
        and cited.source != record.source
    ]


def _ledger_findings(record: EvidenceRecord, journey: JourneyRecord) -> list[Finding]:
    """The honesty ledger against the journey's real steps."""
    steps = {normalize_id(step.surface) for step in journey.steps}
    accounted = {normalize_id(surface) for surface in record.covers} | {
        normalize_id(surface) for surface, _ in record.not_covered
    }
    findings: list[Finding] = []
    stray = sorted(accounted - steps)
    missing = sorted(steps - accounted)
    if stray:
        findings.append(
            Finding(
                code=DOC_JOURNEY_UNRESOLVED,
                location=record.source,
                message=(
                    f"{record.id} accounts for {stray}, which {journey.id} "
                    f"does not take a step to"
                ),
                remediation=(
                    "The ledger says which of the journey's steps this "
                    "transcript reaches. A surface the journey never visits "
                    "belongs in neither half of it — a transcript may run "
                    "more than the journey does, and it does not get to "
                    "claim credit for it."
                ),
            )
        )
    if missing:
        findings.append(
            Finding(
                code=DOC_JOURNEY_UNRESOLVED,
                location=record.source,
                message=(
                    f"{record.id} says nothing about {missing}, which "
                    f"{journey.id} takes a step to"
                ),
                remediation=(
                    "Every step is either covered by this transcript or "
                    "listed in not_covered with the reason it cannot be. "
                    "Silence about a step reads as evidence of it, which is "
                    "the one thing evidence must never do."
                ),
            )
        )
    return findings


def check_evidence_voice(record: EvidenceRecord) -> list[Finding]:
    """Every authored sentence of a fixture is in the product's voice.

    ``DOC_VOICE_VIOLATION``. A fixture is authored prose in the two places
    a person writes one: the intent, and the reason under each uncovered
    step. Both are read by somebody deciding whether to trust the
    evidence, so both are governed by the same rule every other authored
    field is.
    """
    findings: list[Finding] = []
    written: list[tuple[str, str]] = [("intent", record.intent)]
    written.extend(
        (f"not_covered[{surface}].reason", reason) for surface, reason in record.not_covered
    )
    for name, value in written:
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(value)
            if found is None:
                continue
            findings.append(
                Finding(
                    code=DOC_VOICE_VIOLATION,
                    location=record.source,
                    message=(
                        f"{record.id}.{name} uses {found.group(0)!r}, which is "
                        f"{label} and not a word this product uses in text a "
                        f"reader sees"
                    ),
                    remediation=(
                        "write the plain-language term instead. The product "
                        "says feedback data, and it spells its own names with "
                        "a digit zero."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------------


def _program(name: str) -> list[str]:
    """How this process runs one of the :data:`PROGRAMS`.

    The installed console script next to the running interpreter when
    there is one — that is the command a reader types, and running it is
    what makes the transcript evidence of the product rather than of an
    import path. Otherwise the module entry point, which is the same code
    reached the other way.
    """
    if name != "s0ma":  # pragma: no cover - the set has one member today
        raise DocsEvidenceError(f"{name!r} is not a program this replay can run")
    where = Path(sys.executable).parent
    for candidate in (where / "s0ma", where / "s0ma.exe"):
        if candidate.is_file():
            return [str(candidate)]
    return [sys.executable, "-m", "s0ma_dsl"]


#: The environment variables a replayed command keeps, and nothing else.
#: A minimal environment is a determinism decision before it is a security
#: one: a reader's shell carries configuration this product reads, and a
#: transcript recorded with somebody's ``S0MA_*`` knobs set is a
#: transcript of their machine. ``HOME`` is redirected into the throwaway
#: tree for the same reason — a user-level configuration file must not be
#: able to change what a committed transcript says.
_ENV_KEEP: tuple[str, ...] = (
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
)

#: A proxy nothing listens on, in every spelling the ecosystem reads.
#: Best-effort rather than a sandbox, and said so: the real guard is
#: :data:`PROGRAMS`, which is the whole list of things a fixture can
#: start. This is the belt to that pair of braces.
_DEAD_PROXY = "http://127.0.0.1:9"


def _child_env(home: Path) -> dict[str, str]:
    """The environment a replayed command runs in."""
    kept = {name: os.environ[name] for name in _ENV_KEEP if name in os.environ}
    kept["HOME"] = str(home)
    kept["USERPROFILE"] = str(home)
    kept["PYTHONIOENCODING"] = "utf-8"
    for name in ("http_proxy", "https_proxy", "all_proxy"):
        kept[name] = _DEAD_PROXY
        kept[name.upper()] = _DEAD_PROXY
    kept["no_proxy"] = ""
    kept["NO_PROXY"] = ""
    return kept


def _rendered_argv(argv: Sequence[str]) -> str:
    """One command as a reader would have typed it, for the transcript."""
    return " ".join(part if " " not in part else f'"{part}"' for part in argv)


def _version() -> str:
    """The toolchain version this replay ran, read at call time."""
    from s0ma_dsl import __version__

    return __version__


def _run_command(
    step: CommandStep,
    *,
    tmp: Path,
    project: Path,
    cwd: Path,
    version: str,
    timeout_seconds: float,
) -> Observed:
    """One command, run under the house's subprocess discipline.

    ``s0ma.examples.timeout.run_subprocess_with_timeout`` is that
    discipline and this is a deliberate reuse of it rather than a second
    implementation: it decodes as UTF-8 with replacement rather than the
    platform codec, it returns a timeout as a result field instead of an
    exception, and a launch failure comes back structured. All three are
    exactly what a replay wants, and all three were learned the hard way
    on Windows CI.

    Imported here rather than at module scope on purpose. The
    documentation build imports this module for the resolver and must not
    pull an execution stack in behind it — the T3 split is a property of
    the source, not only of the call graph.
    """
    from s0ma.examples.timeout import run_subprocess_with_timeout

    argv = [
        *_program(step.argv[0]),
        *(str(_substitute(part, tmp=tmp, project=project)) for part in step.argv[1:]),
    ]
    result = run_subprocess_with_timeout(
        argv,
        cwd=cwd,
        env=_child_env(tmp),
        timeout_seconds=timeout_seconds,
        # A replay is never a person at a keyboard: hand the child an empty,
        # closed stdin so ``sys.stdin.isatty()`` is False on every platform.
        # Without it a Windows CI runner's inherited console stdin reads as a
        # TTY, and an interactive command (``s0ma feedback``) takes its prompt
        # path and diverges from the committed transcript.
        input_text="",
    )
    return Observed(
        label=f"$ {_rendered_argv(step.argv)}",
        streams=(
            (
                "stdout",
                normalize(result.stdout, tmp=tmp, project=project, version=version),
            ),
            (
                "stderr",
                normalize(result.stderr, tmp=tmp, project=project, version=version),
            ),
        ),
        exit_code=result.returncode,
        structured=None,
        timed_out=result.timed_out,
    )


def _call_tool(server: Any, tool: str, arguments: Mapping[str, Any]) -> tuple[str, Any]:
    """One tool call on the real server, and what came back.

    The server is the one :func:`s0ma_mcp.create_server` builds — no stub,
    no recorded fixture, no transport in between. That is the house idiom
    the self-hosting release gate already uses, and the reason an MCP
    transcript is evidence: the thing that answered is the thing a client
    talks to.

    ``asyncio`` is imported here rather than at module scope for the same
    reason the server is: the tool bindings are coroutines, and a build
    that only ever reads fixtures should not pay for an event loop it
    never starts.
    """
    import asyncio

    answer = asyncio.run(server.call_tool(tool, dict(arguments)))
    blocks: Any = answer
    structured: Any = None
    if isinstance(answer, tuple) and len(answer) == 2:
        blocks, structured = answer
    text = "\n".join(
        str(getattr(block, "text", "")) for block in blocks if getattr(block, "text", None)
    )
    return text, structured


def _server() -> Any:
    """The real authoring server, created in this process.

    Imported here rather than at module scope for two reasons that point
    the same way: s0ma-mcp depends on this package, so a module-scope
    import would be a cycle between distributions, and the documentation
    build imports this module without ever wanting a server. A missing
    server is refused with a sentence rather than an ImportError, because
    "the fixture's channel needs a package this environment does not
    have" is a fact about the environment and not a bug in the fixture.
    """
    try:
        from s0ma_mcp import create_server
    except ImportError as missing:  # pragma: no cover - exercised without the wheel
        raise DocsEvidenceError(
            "an mcp transcript replays against the real authoring server and "
            "s0ma-mcp is not importable here. Install it, or run this fixture "
            "in an environment that has it — there is no stand-in, because a "
            "transcript of a stub is evidence of the stub."
        ) from missing
    return create_server()


def _mcp_environment() -> dict[str, str]:
    """The ``S0MA_*`` knobs removed for the duration of an in-process replay.

    The command channel gets a fresh environment because it starts a
    process; this one cannot, because the server runs here. Removing the
    product's own knobs is the part that matters — telemetry and sink
    overrides change what the server does — and everything is put back
    exactly as it was.
    """
    return {name: os.environ[name] for name in list(os.environ) if name.startswith("S0MA_")}


def replay(
    record: EvidenceRecord,
    *,
    timeout_seconds: float = REPLAY_TIMEOUT_SECONDS,
    version: str | None = None,
) -> Replay:
    """Run one fixture in a throwaway directory and return what it produced.

    Scaffold, then every step in order, then the normalized transcript.
    Nothing outside the temporary tree is read or written, and the tree is
    removed on the way out whatever happened inside it.
    """
    stamp = version if version is not None else _version()
    with tempfile.TemporaryDirectory(
        prefix="s0ma-evidence-", ignore_cleanup_errors=True
    ) as held:
        tmp = Path(held)
        project = tmp if record.scaffold.workdir == "." else tmp / record.scaffold.workdir
        observed: list[Observed] = _scaffold(
            record, tmp=tmp, project=project, version=stamp, timeout_seconds=timeout_seconds
        )
        observed.extend(
            _steps(
                record,
                tmp=tmp,
                project=project,
                version=stamp,
                timeout_seconds=timeout_seconds,
            )
        )
    return Replay(
        record_id=record.id,
        observed=tuple(observed),
        transcript=_transcript(record, tuple(observed)),
    )


def _scaffold(
    record: EvidenceRecord,
    *,
    tmp: Path,
    project: Path,
    version: str,
    timeout_seconds: float,
) -> list[Observed]:
    """Prepare the throwaway project, recording what the preparation said.

    Recorded rather than silent: ``s0ma new project`` is the first thing a
    reader of the first journey ever runs, and a scaffold that started
    failing would otherwise show up as an unrelated divergence three
    commands later.
    """
    if record.scaffold.kind == "authored-tree":
        project.mkdir(parents=True, exist_ok=True)
        for name, text in record.scaffold.files:
            target = tmp.joinpath(*name.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        return [
            Observed(
                label=f"# scaffold: {len(record.scaffold.files)} authored file(s)",
                streams=(),
                exit_code=None,
                structured=None,
                timed_out=False,
            )
        ]
    step = CommandStep(argv=record.scaffold.argv, exit_code=0, stdout=(), stderr=())
    made = _run_command(
        step,
        tmp=tmp,
        project=project,
        cwd=tmp,
        version=version,
        timeout_seconds=timeout_seconds,
    )
    if made.exit_code != 0 or made.timed_out:
        raise DocsEvidenceError(
            f"{record.id}: the scaffold command "
            f"{_rendered_argv(record.scaffold.argv)} exited "
            f"{made.exit_code} and this fixture has nothing to replay "
            f"against.\n{made.stream('stdout')}\n{made.stream('stderr')}"
        )
    return [
        Observed(
            label=f"# scaffold: {_rendered_argv(record.scaffold.argv)}",
            streams=(),
            exit_code=made.exit_code,
            structured=None,
            timed_out=False,
        )
    ]


def _steps(
    record: EvidenceRecord,
    *,
    tmp: Path,
    project: Path,
    version: str,
    timeout_seconds: float,
) -> list[Observed]:
    """Every step of one fixture, in order, on its declared channel."""
    observed: list[Observed] = []
    server: Any = None
    saved = _mcp_environment() if record.channel == CHANNEL_MCP else {}
    for name in saved:
        del os.environ[name]
    try:
        for step in record.steps:
            if isinstance(step, WriteStep):
                target = project.joinpath(*step.path.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(step.text, encoding="utf-8", newline="\n")
                observed.append(
                    Observed(
                        label=f"# write {step.path}",
                        streams=(),
                        exit_code=None,
                        structured=None,
                        timed_out=False,
                    )
                )
                continue
            if isinstance(step, CommandStep):
                observed.append(
                    _run_command(
                        step,
                        tmp=tmp,
                        project=project,
                        cwd=project,
                        version=version,
                        timeout_seconds=timeout_seconds,
                    )
                )
                continue
            if server is None:
                server = _server()
            arguments = {
                key: _substitute(value, tmp=tmp, project=project)
                for key, value in step.arguments
            }
            text, structured = _call_tool(server, step.tool, arguments)
            observed.append(
                Observed(
                    label=f"> {step.tool} {_rendered_arguments(step.arguments)}",
                    streams=(
                        (
                            "text",
                            normalize(text, tmp=tmp, project=project, version=version),
                        ),
                    ),
                    exit_code=None,
                    structured=_normalize_value(
                        structured, tmp=tmp, project=project, version=version
                    ),
                    timed_out=False,
                )
            )
    finally:
        os.environ.update(saved)
    return observed


def _rendered_arguments(arguments: Sequence[tuple[str, Any]]) -> str:
    """A call's arguments as one canonical line."""
    return json.dumps(dict(arguments), sort_keys=True, ensure_ascii=False)


def _transcript(record: EvidenceRecord, observed: Sequence[Observed]) -> str:
    """The whole session as one deterministic text.

    This is what two replays are compared for equality, so everything a
    step produced goes in it — including the structured half of a tool
    result, whose every string has been normalized. A byte that moves
    between two runs turns the determinism gate red here rather than
    turning some fixture flaky later.
    """
    lines: list[str] = [f"# {record.id} ({record.channel})"]
    for item in observed:
        lines.append(item.label)
        if item.exit_code is not None:
            lines.append(f"exit {item.exit_code}")
        for name, text in item.streams:
            lines.append(f"--- {name}")
            lines.extend(text.split("\n"))
        if item.structured is not None:
            lines.append("--- structured")
            lines.extend(
                json.dumps(
                    item.structured, sort_keys=True, indent=2, ensure_ascii=False
                ).split("\n")
            )
    return "\n".join(line.rstrip() for line in lines) + "\n"


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


#: How each kind of expectation reads in a failure message. Written out
#: rather than interpolated from the field, because "no line at or after
#: line 6 containss ..." is what interpolating it gives you.
_READS: Mapping[str, str] = {
    "absent": "must never appear",
    "contains": "contains",
    "line": "is a whole line equal to",
    "regex": "matches",
}


def _line_of(text: str, offset: int) -> int:
    """The one-based line ``offset`` falls on."""
    return text.count("\n", 0, offset) + 1


def _at(text: str, offset: int) -> str:
    """The line the search had reached, for a failure message."""
    if offset >= len(text):
        return "<end of output>"
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start : end if end != -1 else len(text)].strip()


def _advance(expectation: Expectation, text: str, offset: int) -> int | None:
    """Where the search reaches after this expectation, or ``None`` if it does not.

    A **character** cursor rather than a line cursor, and the difference
    matters twice a fixture: a structured result arrives as one long line
    of JSON, so two fragments an author writes in order are often on the
    same line, and a line cursor would refuse the second one for being
    where the first was. Whole-line expectations still consume their line
    — two of them naming the same line is a mistake, not a coincidence —
    while a fragment carries on from where it matched.
    """
    if expectation.match == "contains":
        found = text.find(expectation.text, offset)
        return None if found == -1 else found + len(expectation.text)
    if expectation.match == "regex":
        matched = re.compile(expectation.text).search(text, offset)
        return None if matched is None else max(matched.end(), matched.start() + 1)
    start = text.rfind("\n", 0, offset) + 1
    for line in text[start:].split("\n"):
        if line == expectation.text:
            return start + len(line) + 1
        start += len(line) + 1
    return None


def _stream_divergence(
    stream: str, expectations: Sequence[Expectation], text: str
) -> Divergence | None:
    """The first expectation this stream does not satisfy, and where.

    Ordered: each expectation is searched for at or after where the
    previous one matched, so output that arrived in a different order is
    a divergence rather than a pass — which is most of what makes a
    transcript a transcript. ``absent`` is the exception and looks at the
    whole stream, because "this never appears" is not a position.
    """
    cursor = 0
    for index, expectation in enumerate(expectations):
        if expectation.match == "absent":
            found = text.find(expectation.text)
            if found == -1:
                continue
            return Divergence(
                step=0,
                stream=stream,
                expectation=index,
                line=_line_of(text, found),
                detail=(
                    f"{expectation.text!r} {_READS['absent']} and line "
                    f"{_line_of(text, found)} is {_at(text, found)!r}"
                ),
            )
        reached = _advance(expectation, text, cursor)
        if reached is None:
            return Divergence(
                step=0,
                stream=stream,
                expectation=index,
                line=_line_of(text, cursor),
                detail=(
                    f"nothing at or after line {_line_of(text, cursor)} "
                    f"{_READS[expectation.match]} {expectation.text!r}; the "
                    f"search had reached {_at(text, cursor)!r}"
                ),
            )
        cursor = reached
    return None


def _lookup(structured: Any, path: str) -> tuple[bool, Any]:
    """The value at ``path``, and whether there was one."""
    held = structured
    for segment in path.split("."):
        if isinstance(held, dict):
            if segment not in held:
                return False, None
            held = held[segment]
            continue
        if isinstance(held, list) and segment.isdigit():
            index = int(segment)
            if index >= len(held):
                return False, None
            held = held[index]
            continue
        return False, None
    return True, held


def _field_divergence(
    expectations: Sequence[FieldExpectation], structured: Any
) -> Divergence | None:
    """The first structured field that does not hold what was declared."""
    for index, expectation in enumerate(expectations):
        found, value = _lookup(structured, expectation.path)
        if not found:
            return Divergence(
                step=0,
                stream="fields",
                expectation=index,
                line=0,
                detail=f"the result has no {expectation.path}",
            )
        if value != expectation.equals:
            return Divergence(
                step=0,
                stream="fields",
                expectation=index,
                line=0,
                detail=(
                    f"{expectation.path} is {value!r} and the fixture says "
                    f"{expectation.equals!r}"
                ),
            )
    return None


def _step_divergence(step: Step, item: Observed) -> Divergence | None:
    """Everything one step claims, checked against what it produced."""
    if isinstance(step, WriteStep):
        return None
    if item.timed_out:
        return Divergence(
            step=0,
            stream="exit",
            expectation=0,
            line=0,
            detail="the command was still running when the replay's timeout fired",
        )
    if isinstance(step, CommandStep):
        if item.exit_code != step.exit_code:
            return Divergence(
                step=0,
                stream="exit",
                expectation=0,
                line=0,
                detail=f"exited {item.exit_code} and the fixture says {step.exit_code}",
            )
        for name, expectations in (("stdout", step.stdout), ("stderr", step.stderr)):
            found = _stream_divergence(name, expectations, item.stream(name))
            if found is not None:
                return found
        return None
    found = _stream_divergence("text", step.text, item.stream("text"))
    if found is not None:
        return found
    return _field_divergence(step.fields, item.structured)


def compare(record: EvidenceRecord, ran: Replay) -> Verification:
    """Check one replay against the fixture that declared it. Pure.

    Separated from :func:`replay` on purpose, and the purpose is that a
    comparison nobody has to run a toolchain for can be exercised
    anywhere — including inside the negative battery, which fires
    ``DOC_EXAMPLE_FAILED`` against a captured transcript in microseconds
    and needs no temporary directory to do it.
    """
    steps = tuple(record.steps)
    ran_steps = ran.observed[1:]
    if len(ran_steps) != len(steps):
        return _failed(
            record,
            ran,
            Divergence(
                step=len(ran_steps),
                stream="exit",
                expectation=0,
                line=0,
                detail=(
                    f"the fixture declares {len(steps)} step(s) and this "
                    f"replay produced {len(ran_steps)}"
                ),
            ),
        )
    for index, (step, item) in enumerate(zip(steps, ran_steps, strict=True)):
        found = _step_divergence(step, item)
        if found is None:
            continue
        located = Divergence(
            step=index,
            stream=found.stream,
            expectation=found.expectation,
            line=found.line,
            detail=found.detail,
        )
        return _failed(record, ran, located)
    return Verification(
        record_id=record.id, ok=True, divergence=None, findings=(), replay=ran
    )


def _failed(record: EvidenceRecord, ran: Replay, found: Divergence) -> Verification:
    """One diverged replay as a finding a person can act on."""
    label = ran.observed[found.step + 1].label if found.step + 1 < len(ran.observed) else ""
    return Verification(
        record_id=record.id,
        ok=False,
        divergence=found,
        findings=(
            Finding(
                code=DOC_EXAMPLE_FAILED,
                location=record.source,
                message=(
                    f"{record.id} no longer replays: {found.rendered()}"
                    + (f" [{label}]" if label else "")
                ),
                remediation=(
                    f"Run the fixture and read what it actually printed. "
                    f"Either the product changed and {record.journey} now "
                    f"reads a step differently — in which case the guide is "
                    f"wrong too, which is what this gate is for — or the "
                    f"expectation was written more tightly than the output "
                    f"ever was. Never loosen it to a pattern that would pass "
                    f"on a broken run."
                ),
            ),
        ),
        replay=ran,
    )


def verify(
    record: EvidenceRecord,
    *,
    timeout_seconds: float = REPLAY_TIMEOUT_SECONDS,
    version: str | None = None,
) -> Verification:
    """Replay one fixture and compare it against what it declares."""
    return compare(
        record, replay(record, timeout_seconds=timeout_seconds, version=version)
    )


def verify_all(
    library: EvidenceLibrary,
    *,
    timeout_seconds: float = REPLAY_TIMEOUT_SECONDS,
) -> tuple[Verification, ...]:
    """Every fixture in ``library``, replayed in id order."""
    return tuple(
        verify(record, timeout_seconds=timeout_seconds)
        for record in sorted(library.records, key=lambda record: record.id)
    )


def passing(verifications: Iterable[Verification]) -> tuple[str, ...]:
    """The ids that replayed green, sorted — the *executed* half of T3.

    Shaped like an
    :data:`~s0ma_dsl.docs_model.validate.EvidenceResolver`'s answer on
    purpose: the suite compares this against what
    :meth:`EvidenceLibrary.resolver` resolved, and the two being equal is
    what stops a fixture being resolved by the build and run by nobody.
    """
    return tuple(sorted(item.record_id for item in verifications if item.ok))
