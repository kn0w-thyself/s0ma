"""Authored journeys, read from the files a person writes them in.

Milestone E1 of the docs-function plan (internal) §10, task T1. One file
per journey under ``docs/s0ma_src/journeys/``, read here, validated here,
turned into :class:`~s0ma_dsl.docs_model.records.JourneyRecord` values
here.

**Why a journey is data and not a declaration.** D-4 is a strict
no-new-DSL ruling and §2.2 says journeys are data. B6 tried the hard cases
as data first, as §2.2.6 requires, and catalog-side binding proved
sufficient; B7 then wrote two more journeys on channels B4 never touched
and needed no schema change at all. This milestone inherits that verdict
and adds nothing to the language: a journey is a JSON object, the loader
is the reading of it, and the only thing an author has to learn is the
shape of the file. The ``sequence`` declaration §2.2.6 conditionally
pre-authorized is **not** invoked, and nothing here wanted it.

**One file per journey.** Not one file holding all of them, for a reason
that is about people rather than about parsing: E3, E5, E6 and E7 each
author one journey, and a single file would make four milestones edit one
set of lines. The file's stem is the journey's slug, checked, so a reader
looking for ``journey:first-project`` opens ``first-project.json`` and a
file renamed without its record is refused rather than silently orphaned.

**Refusal versus finding**, the line C5a drew and this module keeps:

* a file that does not satisfy its own schema — a missing key, an id that
  matches no form, a step naming something that is not a served
  capability, a teaching order that says one concept twice — raises
  :class:`DocsJourneysError`, naming the JSON path of the offending
  value. Nothing can be built from it, so nothing is;
* something wrong with the *content* — a word the product voice does not
  use — is a :class:`~s0ma_dsl.docs_model.providers.Finding`, collected so
  an author sees every one of them in a single run.

The gates that need the whole composition — do the steps resolve, is the
teaching order sound, is an approval boundary declared where one is
crossed, did the evidence run — are not here. They are
:func:`~s0ma_dsl.docs_model.validate.check_journeys`, because each of them
needs surfaces and concepts this provider has never seen.

**Nothing here writes, and nothing here opens a socket.** Every path is
repository-relative POSIX (INV-5), and every digest is over LF-normalized
UTF-8, so a record carries no trace of the machine that built it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import id_form, validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    Finding,
    ProviderResult,
    SourcedRecord,
    sort_findings,
    sort_records,
)
from s0ma_dsl.docs_model.providers_concepts import (
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    ExampleRef,
    JourneyRecord,
    JourneyStep,
    Provenance,
    RecoveryPath,
    authored_prose_fields,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "JOURNEYS_DIR",
    "JOURNEYS_SCHEMA",
    "JOURNEY_FLOORS",
    "NOT_A_SURFACE",
    "ONE_LINE_FIELDS",
    "DocsJourneysError",
    "JourneysProvider",
    "check_journey_voice",
]

#: The authored file's own schema. Not the model's, for C5a's reason: a
#: journey file is an input to the documentation model rather than a
#: serialization of it, and one version string over both would make a
#: change to either look like a change to both.
JOURNEYS_SCHEMA = "s0ma-docs-journeys@1"

#: Where authored journeys live, repository-relative (ADR-012).
JOURNEYS_DIR = "docs/s0ma_src/journeys"

#: The anti-vacuity floor, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Three is what
#: E1 migrates from the B-phase prototypes, and it is deliberately the
#: exact count rather than an honest minimum under it: E3 to E7 each add
#: one, so the number only ever goes up, and a floor at three catches the
#: failure that matters — the directory moved, or the loader has stopped
#: seeing it. Seven since beta-prep-1-retrofit F2a wrote
#: ``journey:retrofit-existing-codebase``.
JOURNEY_FLOORS: Mapping[tuple[str, str], int] = {("journeys", "journeys"): 7}

#: Id forms a journey step may not name, each with where it belongs
#: instead. B7 finding 4 is why this exists: a step naming ``concept:nerve``
#: used to report "surface concept:nerve does not resolve", which sends an
#: author looking for a missing surface rather than telling them that
#: ordered teaching over concepts is a different record.
#:
#: A refusal list rather than an allow-list of served forms, on purpose.
#: The weakest check that catches the defect is the one that does not have
#: to be edited every time the product grows a channel — an allow-list
#: would turn a new served kind into a mysterious refusal here, and a form
#: nobody has classified still reaches the resolver, which reports it
#: honestly as something this build does not address.
#: Two of the six are not other *kinds* of record but records the model
#: does call surfaces — a configuration key and a diagnostic code both
#: compose as :class:`~s0ma_dsl.docs_model.records.SurfaceRecord` values.
#: They are refused here anyway, and the reason is the one D2 wrote down
#: when it minted their channels and
#: :data:`~s0ma_dsl.docs_model.validate.CHANNEL_EFFECTS` classified them
#: ``False``: each *names a thing* rather than a way to reach one. A step
#: is something a reader does, so a step naming one would resolve
#: perfectly and lead nowhere — the exact failure that survives a
#: resolution gate.
NOT_A_SURFACE: Mapping[str, str] = {
    "concept": (
        "a concept is taught, not called. A journey step names a capability "
        "the reader reaches; ordered teaching over concepts is what "
        "JourneyRecord.concepts_taught and the sequence: records carry."
    ),
    "journey": (
        "a journey is not a step of another journey. Name the surfaces the "
        "other path uses, or leave the reader a pointer in the prose."
    ),
    "sequence": (
        "a teaching order is not something a reader invokes. Its topics "
        "belong in concepts_taught if this path teaches them."
    ),
    "doc": (
        "a document is read, not called. A catalog row's covers list is "
        "where a document says it is about this journey."
    ),
    "authority": (
        "an authority governs a claim; it is not a step. A journey cites "
        "one through the records it is composed with, not through a step."
    ),
    "example": (
        "an example is evidence that the path works, not a step along it. "
        "Name it in evidence."
    ),
    "config": (
        "a configuration key is set once in a project's own table, not "
        "called at a point on a path. If the step is about configuring, "
        "name the capability that reads the key."
    ),
    "diagnostic": (
        "a diagnostic is something that happens to a reader, not something "
        "they do. A failure a path recovers from is named in a recovery "
        "path's when, and the capability they go back to is its "
        "next_surface."
    ),
}

#: The authored fields written one to a line by every channel that shows
#: them — a step's purpose is a bullet on a page and an item in a list on
#: the agent channel. A line feed inside one would split a single fact
#: across two bullets on the way out and merge back as something else on
#: the way in, so it is refused where it is written rather than repaired
#: where it is read.
ONE_LINE_FIELDS: tuple[str, ...] = (
    "action",
    "approval_boundary",
    "expected_outcome",
    "purpose",
    "when",
)


class DocsJourneysError(DocsProviderError):
    """An authored journey file does not satisfy the journeys schema.

    Raised rather than reported, for the reason
    :class:`~s0ma_dsl.docs_model.providers.DocsProviderError` exists: a
    file whose shape is wrong yields no record at all, so continuing would
    mean composing a bundle silently missing a journey. Every message
    names the JSON path of the value that is wrong.
    """


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


def _digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    The same computation C4, C5a and C6 make, so that four providers
    reading one tree agree about what a file hashes to.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        raise DocsJourneysError(f"{where}: expected an object, got {_named(value)}")
    return value


def _array(value: Any, where: str) -> list[Any]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise DocsJourneysError(f"{where}: expected a list, got {_named(value)}")
    return value


def _text(value: Any, where: str) -> str:
    """``value`` as a non-empty string, refusing anything else by name."""
    if not isinstance(value, str):
        raise DocsJourneysError(f"{where}: expected text, got {_named(value)}")
    if not value.strip():
        raise DocsJourneysError(
            f"{where}: is empty. An empty field is not the same as an absent "
            f"one, and this model has nowhere to put an unwritten fact."
        )
    return value


def _optional_text(value: Any, where: str) -> str:
    """``value`` as text that may be empty, refusing anything else by name.

    One field uses it — ``approval_boundary`` — and empty there is an
    answer rather than a silence: it says this step asks the reader for
    nothing irreversible. The gate reads the surface's own effects to
    decide whether that answer is true.
    """
    if not isinstance(value, str):
        raise DocsJourneysError(f"{where}: expected text, got {_named(value)}")
    return value


def _one_line(value: str, name: str, where: str) -> str:
    """Refuse a line feed in a field written one to a line."""
    if name in ONE_LINE_FIELDS and "\n" in value:
        raise DocsJourneysError(
            f"{where}: contains a line break. Every channel writes this "
            f"field as one item on one line, so a break inside it would "
            f"leave the page and the record disagreeing about how many "
            f"things were said. Write it as one line."
        )
    return value


def _exactly(raw: Mapping[str, Any], expected: Sequence[str], where: str) -> None:
    """Refuse an object that does not carry exactly the expected keys.

    An unknown key and a missing key are both errors, for C1's reason: a
    reader that tolerated a stray key would silently drop what an author
    wrote, and this whole model exists against that.
    """
    unknown = sorted(set(raw) - set(expected))
    missing = sorted(set(expected) - set(raw))
    if unknown or missing:
        raise DocsJourneysError(
            f"{where}: does not match the {JOURNEYS_SCHEMA} shape "
            f"(unexpected: {unknown}, absent: {missing})"
        )


_JOURNEY_KEYS = (
    "concepts_required",
    "concepts_taught",
    "evidence",
    "id",
    "intent",
    "recovery_paths",
    "steps",
)
_STEP_KEYS = ("approval_boundary", "expected_outcome", "purpose", "surface")
_RECOVERY_KEYS = ("action", "next_surface", "when")
_EVIDENCE_KEYS = ("id", "source")


# ---------------------------------------------------------------------------
# What one reading produced
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    """One reading of the whole directory, cached so it happens once."""

    records: tuple[SourcedRecord, ...]
    findings: tuple[Finding, ...]


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JourneysProvider:
    """Every authored journey of one checkout, read as records.

    ``root`` is the repository and ``relative`` is the directory the files
    live in. Both are fixed when the provider is built and neither is
    re-resolved at call time, which is what the provider contract asks for
    and what makes two calls in one process provably equal.

    One provider for the whole directory rather than one per file, unlike
    :class:`~s0ma_dsl.docs_model.providers_concepts.ConceptsProvider`. The
    difference is that a concepts file declares a *domain* and there are
    two of them by design, whereas journeys are one family that grows a
    file at a time — and a per-file provider would mean E3 through E7 each
    had to register themselves in the composition, which is exactly the
    kind of step that gets forgotten and leaves a journey composed by
    nobody.
    """

    root: Path
    relative: str = JOURNEYS_DIR
    _cache: dict[str, _Loaded] = field(default_factory=dict, compare=False, repr=False)

    @property
    def provider_id(self) -> str:
        """This adapter's stable id."""
        return "journeys"

    # -- the public reading ------------------------------------------------

    def provide(self) -> ProviderResult:
        """Every journey in the directory, sorted."""
        return ProviderResult(
            provider_id=self.provider_id, records=sort_records(self._load().records)
        )

    def findings(self) -> tuple[Finding, ...]:
        """What is wrong with the files' content, in reporting order.

        Separate from :meth:`provide` because the provider contract has
        nowhere to put a finding: a result is records. These are the
        problems an author fixes without the composition having to run.
        """
        return self._load().findings

    # -- reading -----------------------------------------------------------

    def _files(self) -> tuple[Path, ...]:
        """Every journey file, in name order, refusing an absent directory."""
        directory = self.root / self.relative
        if not directory.is_dir():
            raise DocsJourneysError(
                f"{self.relative} is not a directory in this checkout. The "
                f"authored journeys live there, one file per journey; a "
                f"directory nothing answers to cannot be read."
            )
        return tuple(sorted(directory.glob("*.json")))

    def _load(self) -> _Loaded:
        """Read the directory once and remember it."""
        held = self._cache.get(self.relative)
        if held is None:
            held = self._read()
            self._cache[self.relative] = held
        return held

    def _read(self) -> _Loaded:
        """The whole reading: every file, in name order."""
        records: list[SourcedRecord] = []
        findings: list[Finding] = []
        seen: dict[str, str] = {}
        for path in self._files():
            relative = f"{self.relative}/{path.name}"
            text = path.read_text(encoding="utf-8")
            record = self._read_file(text, relative, path.stem)
            held = seen.get(record.id)
            if held is not None:
                raise DocsJourneysError(
                    f"{relative}#/record/id: {record.id} is already declared "
                    f"by {held}. One journey, one file — two files under one "
                    f"id would reach the merge rule as a disagreement with "
                    f"itself."
                )
            seen[record.id] = relative
            stamp = Provenance(
                adapter_id=self.provider_id,
                schema_version=SCHEMA,
                source=relative,
                source_sha256=_digest_of(text),
            )
            records.append(SourcedRecord(record=record, provenance=stamp))
            findings.extend(check_journey_voice(record, relative))
        return _Loaded(records=tuple(records), findings=sort_findings(findings))

    def _read_file(self, text: str, relative: str, stem: str) -> JourneyRecord:
        """One file as one record, refusing every shape it is not."""
        try:
            document = json.loads(text)
        except json.JSONDecodeError as broken:
            raise DocsJourneysError(
                f"{relative}: is not readable as JSON ({broken.msg} at line "
                f"{broken.lineno}, column {broken.colno})"
            ) from broken

        raw = _object(document, relative)
        _exactly(raw, ("record", "schema"), relative)
        schema = _text(raw["schema"], f"{relative}#/schema")
        if schema != JOURNEYS_SCHEMA:
            raise DocsJourneysError(
                f"{relative}#/schema: this loader reads {JOURNEYS_SCHEMA!r}; "
                f"the file names {schema!r}"
            )
        record = _read_journey(raw["record"], f"{relative}#/record")
        if record.id != f"journey:{stem}":
            raise DocsJourneysError(
                f"{relative}#/record/id: the file is named {stem}.json and the "
                f"record is {record.id!r}. The file's stem is the journey's "
                f"slug, so a reader looking for {record.id} opens the file "
                f"that holds it; make them agree."
            )
        return record


# ---------------------------------------------------------------------------
# One journey, read
# ---------------------------------------------------------------------------


def _read_journey(entry: Any, where: str) -> JourneyRecord:
    """One authored journey as a record, every reference checked in form."""
    item = _object(entry, where)
    _exactly(item, _JOURNEY_KEYS, where)

    identifier = _text(item["id"], f"{where}/id")
    if id_form(identifier) != "journey":
        raise DocsJourneysError(
            f"{where}/id: {identifier!r} is not a journey id. An authored "
            f"path through several surfaces is addressed by a lowercase "
            f"hyphenated slug — journey:first-project."
        )
    validate_id(identifier)

    steps = _read_steps(item["steps"], f"{where}/steps", identifier)
    return JourneyRecord(
        id=identifier,
        intent=_text(item["intent"], f"{where}/intent"),
        steps=steps,
        recovery_paths=_read_recovery(item["recovery_paths"], f"{where}/recovery_paths"),
        concepts_taught=_read_taught(item["concepts_taught"], f"{where}/concepts_taught"),
        concepts_required=_read_required(
            item["concepts_required"], f"{where}/concepts_required"
        ),
        evidence=_read_evidence(item["evidence"], f"{where}/evidence"),
    )


def _read_steps(raw: Any, where: str, journey_id: str) -> tuple[JourneyStep, ...]:
    """The ordered steps, each naming something a reader can actually reach."""
    entries = _array(raw, where)
    if not entries:
        raise DocsJourneysError(
            f"{where}: is empty. A journey with no steps is a title; it "
            f"passes every check it is subject to and leads no one anywhere."
        )
    found: list[JourneyStep] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        item = _object(entry, at)
        _exactly(item, _STEP_KEYS, at)
        surface = _text(item["surface"], f"{at}/surface")
        _check_surface(surface, f"{at}/surface", journey_id)
        found.append(
            JourneyStep(
                surface=surface,
                purpose=_one_line(
                    _text(item["purpose"], f"{at}/purpose"), "purpose", f"{at}/purpose"
                ),
                expected_outcome=_one_line(
                    _text(item["expected_outcome"], f"{at}/expected_outcome"),
                    "expected_outcome",
                    f"{at}/expected_outcome",
                ),
                approval_boundary=_one_line(
                    _optional_text(item["approval_boundary"], f"{at}/approval_boundary"),
                    "approval_boundary",
                    f"{at}/approval_boundary",
                ),
            )
        )
    return tuple(found)


def _check_surface(surface: str, where: str, journey_id: str) -> None:
    """A step names a served capability, and says so if it does not."""
    form = id_form(surface)
    instead = NOT_A_SURFACE.get(form or "")
    if instead is not None:
        raise DocsJourneysError(
            f"{where}: {journey_id} takes a step to {surface}, and {instead}"
        )
    validate_id(surface)


def _read_recovery(raw: Any, where: str) -> tuple[RecoveryPath, ...]:
    """What to do when a named failure happens, in the order written."""
    entries = _array(raw, where)
    found: list[RecoveryPath] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        item = _object(entry, at)
        _exactly(item, _RECOVERY_KEYS, at)
        when = _one_line(_text(item["when"], f"{at}/when"), "when", f"{at}/when")
        if when in seen:
            raise DocsJourneysError(
                f"{at}/when: {when} already has a recovery path. One failure, "
                f"one answer — two would leave a reader choosing between them "
                f"at the moment they are least able to."
            )
        seen.add(when)
        next_surface = _text(item["next_surface"], f"{at}/next_surface")
        _check_surface(next_surface, f"{at}/next_surface", when)
        found.append(
            RecoveryPath(
                when=when,
                next_surface=next_surface,
                action=_one_line(
                    _text(item["action"], f"{at}/action"), "action", f"{at}/action"
                ),
            )
        )
    return tuple(found)


def _read_taught(raw: Any, where: str) -> tuple[str, ...]:
    """The teaching order: concept ids, as written, each said once.

    Deliberately **not** sorted, unlike every other id list this model
    reads. The order is the content — the whole teaching rule is that a
    concept comes before anything resting on it — so sorting here would
    throw away the only thing the field says. What is refused instead is a
    repeat, for the reason
    :data:`~s0ma_dsl.docs_model.validate.DOC_SEQUENCE_REPEATS` exists: a
    teaching order that names one concept twice has lost its order
    somewhere.
    """
    entries = _array(raw, where)
    found: list[str] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        identifier = _text(entry, at)
        if id_form(identifier) != "concept":
            raise DocsJourneysError(
                f"{at}: {identifier!r} is not a concept id. A journey teaches "
                f"ideas, addressed by their term as a lowercase hyphenated "
                f"slug — concept:self-knowledge."
            )
        validate_id(identifier)
        if identifier in found:
            raise DocsJourneysError(
                f"{at}: {identifier} is taught twice. A teaching order names "
                f"each concept once, at the place it is actually taught; if "
                f"the second mention is a different lesson, it is a different "
                f"concept and needs its own record."
            )
        found.append(identifier)
    return tuple(found)


def _read_required(raw: Any, where: str) -> tuple[str, ...]:
    """What the reader is assumed to know already: a sorted set of ids."""
    entries = _array(raw, where)
    found: list[str] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        identifier = _text(entry, at)
        if id_form(identifier) != "concept":
            raise DocsJourneysError(
                f"{at}: {identifier!r} is not a concept id. A prerequisite is "
                f"an idea the reader already has, addressed the same way "
                f"every other idea is."
            )
        validate_id(identifier)
        if identifier in found:
            raise DocsJourneysError(f"{at}: {identifier} is listed twice")
        found.append(identifier)
    if found != sorted(found):
        raise DocsJourneysError(
            f"{where}: is not sorted. Nothing about a prerequisite is "
            f"ordered — it is what you know before step one — and a sorted "
            f"list is what makes two readings of this file byte-identical."
        )
    return tuple(found)


def _read_evidence(raw: Any, where: str) -> tuple[ExampleRef, ...]:
    """The executable evidence that this path still works, sorted by id."""
    entries = _array(raw, where)
    found: list[ExampleRef] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        item = _object(entry, at)
        _exactly(item, _EVIDENCE_KEYS, at)
        identifier = _text(item["id"], f"{at}/id")
        if id_form(identifier) != "example":
            raise DocsJourneysError(
                f"{at}/id: {identifier!r} is not an example id. Evidence is "
                f"a registered runnable example or transcript fixture, and it "
                f"takes one colon, always — the doubled form is the authoring "
                f"syntax for an entity reference inside prose."
            )
        found.append(
            ExampleRef(id=identifier, source=_text(item["source"], f"{at}/source"))
        )
    ids = [held.id for held in found]
    if ids != sorted(ids):
        raise DocsJourneysError(f"{where}: is not sorted by id")
    if len(set(ids)) != len(ids):
        raise DocsJourneysError(f"{where}: names one piece of evidence twice")
    return tuple(found)


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


def check_journey_voice(record: JourneyRecord, location: str) -> list[Finding]:
    """Every authored prose field of a journey is in the product's voice.

    ``DOC_VOICE_VIOLATION``.
    The fields are the ones C1 classifies ``AUTHORED_PROSE``, read from
    :data:`~s0ma_dsl.docs_model.records.FIELD_CLASS` rather than listed
    here, so a field added to any of the three record types is governed
    the moment it is classified. Three types are walked because a journey
    is three types deep: the path's own intent, each step's purpose,
    expected outcome and approval boundary, and each recovery path's
    condition and action are all sentences a reader reads.

    Nothing a provider derived is walked, because a journey has nothing
    derived in it — every word here was written by a person, which is what
    makes the rule reach all of it rather than part of it.
    """
    findings: list[Finding] = []
    written: list[tuple[str, Any]] = [(f"{record.id}", record)]
    for index, step in enumerate(record.steps):
        written.append((f"{record.id}.steps[{index}]", step))
    for index, path in enumerate(record.recovery_paths):
        written.append((f"{record.id}.recovery_paths[{index}]", path))
    for name, held in written:
        for attribute in authored_prose_fields(type(held)):
            value = getattr(held, attribute)
            if not isinstance(value, str):
                continue
            findings.extend(_voice_findings(name, attribute, value, location))
    return findings


def _voice_findings(name: str, attribute: str, value: str, location: str) -> list[Finding]:
    """One ``DOC_VOICE_VIOLATION`` per forbidden word in one field."""
    findings: list[Finding] = []
    for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
        found = pattern.search(value)
        if found is None:
            continue
        findings.append(
            Finding(
                code=DOC_VOICE_VIOLATION,
                location=location,
                message=(
                    f"{name}.{attribute} uses {found.group(0)!r}, which is "
                    f"{label} and not a word this product uses in text a "
                    f"reader sees"
                ),
                remediation=(
                    "write the plain-language term instead. The product says "
                    "feedback data, and it spells its own names with a digit "
                    "zero. Every word of a journey is authored, so the rule "
                    "reaches all of it."
                ),
            )
        )
    return findings
