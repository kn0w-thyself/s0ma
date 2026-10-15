"""The document catalog: every document this repository keeps, as records.

Milestone C6 of the docs-function plan (internal) §8. The catalog is the
successor to the A6 classification ledger
(``docs/s0ma_src/doc-classification.json``): the ledger answered "is every
tracked Markdown file classified", and the catalog answers that *and* what
each document is, who it is for, where its words actually live, which
written authority it is, and what it covers.

**Why a data file.** B6 compared the two forms arch §8.6 asked it to
compare — a ``.s0ma`` module of catalog cells against a schema-validated
data file read by a registered provider — and ruled for the data file
(D-4 strict: no new grammar). ADR-012 ruled on where it lives:
``docs/s0ma_src/``, with the reusable machinery here in ``s0ma_dsl``. So
:data:`CATALOG_FILE` is the authored source and this module is the reading
of it.

**What the file carries that a record does not.** ``kind``, ``status`` and
``audiences`` are catalog facts (arch §6.5) that ``@1``'s
:class:`~s0ma_dsl.docs_model.records.DocumentRecord` does not yet declare —
B4 deferred them because no gate branched on them, and C1 kept the
deferral. They earn their place *here* because three gates in this module
read them, and they reach the model through the one field C6 was scheduled
to re-add: :attr:`DocumentRecord.authority`. Nothing is smuggled into the
record type; the file is richer than the record, and the projection is
this module's job.

**Identity.** A row's id is ``doc:<category>/<slug>``. The category is a
fact about the document's standing — ``normative``, ``guide``,
``generated``, ``mirror``, ``historical``, ``pointer``, ``plan``,
``spike`` — and :data:`STATUS_BY_CATEGORY` makes the id and the row's
``status`` check each other, so an id cannot quietly say one thing while
the row says another. The slug is derived from the filename rather than
from the whole path, because a filename is the part of a path that
survives a move and Phase G is going to move a great many of these.

**Refusal versus finding**, the line C5a drew and this module keeps:

* a file that does not satisfy its own schema — a missing key, an id that
  matches no form, a status outside the enum, a row naming a file that is
  not in the checkout — raises :class:`DocsCatalogError` naming the JSON
  path of the offending value. Nothing can be built from it, so nothing is;
* something wrong with the *corpus* — a tracked document nobody cataloged,
  two rows claiming one file, a cited authority no provider emits — is a
  :class:`~s0ma_dsl.docs_model.providers.Finding`, collected so a person
  sees every one of them in a single run.

**The completeness gate takes its corpus as an argument.** ``provide()``
reads one file and the files that file names, and nothing else; asking git
what it tracks is a separate call (:func:`tracked_markdown`) feeding a
separate gate (:func:`check_completeness`). Keeping them apart is what lets
the gate be tested against a fixture corpus, and keeps the provider itself
a reading rather than a process.

**Nothing here writes, and nothing here opens a socket.** Every path a
record carries is repository-relative POSIX (INV-5) and every digest is
over LF-normalized UTF-8.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import id_form, normalize_id, validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    Finding,
    ProviderResult,
    SourcedRecord,
    sort_findings,
    sort_records,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    DocsBundle,
    DocumentRecord,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

__all__ = [
    "AUDIENCES",
    "CATALOG_FILE",
    "CATALOG_FLOORS",
    "CATALOG_SCHEMA",
    "DOC_CANONICAL_DUPLICATE",
    "DOC_DOCUMENT_UNCATALOGED",
    "DOC_TOPIC_UNRESOLVED",
    "KINDS",
    "PROVIDER_ID",
    "PROSE_FRAGMENT_KINDS",
    "STATUSES",
    "STATUS_BY_CATEGORY",
    "CatalogProvider",
    "CatalogRow",
    "DocsCatalogError",
    "Exclusion",
    "check_canonical_sources",
    "check_completeness",
    "check_document_authorities",
    "tracked_markdown",
]

#: The authored file's own schema. Not the model's: a catalog is an input
#: to the documentation model, not a serialization of it, and one version
#: string for both would make a change to either look like a change to
#: both. The same separation C5a made for concepts.
CATALOG_SCHEMA = "s0ma-docs-catalog@1"

#: Where the catalog lives, repository-relative (ADR-012 §1).
CATALOG_FILE = "docs/s0ma_src/catalog.json"

#: This adapter's id. One catalog, one provider, one id.
PROVIDER_ID = "catalog"

#: What a document is for a reader (arch §6.5). Closed: a kind nobody can
#: name is a kind no navigation can group by, and arch §9.1's information
#: architecture is built from these.
KINDS: tuple[str, ...] = (
    "contributing",
    "guide",
    "historical",
    "normative",
    "operations",
    "reference",
    "tutorial",
)

#: What standing a document has (arch §6.5), plus one addition this
#: milestone makes and names: ``working-plan``.
#:
#: Arch §6.5 lists six statuses and the A6 ledger's frozen disposition enum
#: (plan §5) lists eight dispositions. Seven of the eight map onto a status
#: one-for-one; ``working-plan`` maps onto none of the six, and dropping
#: those rows would have cost the completeness gate its whole point — a
#: plan is a tracked Markdown file, so a catalog that could not hold one
#: could never claim to cover the corpus. Calling a plan ``living`` would
#: be worse: it would promise a document is maintained when the whole point
#: of a plan is that it stops being true the day its milestones land.
STATUSES: tuple[str, ...] = (
    "generated",
    "historical",
    "living",
    "mirror",
    "normative",
    "superseded",
    "working-plan",
)

#: Who a document is written for. The A6 ledger's vocabulary minus
#: ``machine``, which in that ledger labels only the three test fixtures
#: the catalog excludes.
AUDIENCES: tuple[str, ...] = ("agent", "contributor", "owner", "user")

#: The status each id category asserts. This is what makes an id a claim
#: rather than a label: a row filed under ``doc:normative/`` whose status
#: says ``historical`` is refused, because one of the two is wrong and the
#: file cannot say which.
#:
#: Two categories share the ``working-plan`` status. That is deliberate and
#: it is the one place the id form draws a distinction the disposition enum
#: does not: a plan under ``plans/`` and a spike note under
#: ``scripts/spikes/`` have the same standing and are not the same kind of
#: thing to go looking for.
STATUS_BY_CATEGORY: Mapping[str, str] = {
    "catalog": "living",
    "generated": "generated",
    "guide": "living",
    "historical": "historical",
    "mirror": "mirror",
    "normative": "normative",
    "plan": "working-plan",
    "pointer": "superseded",
    "spike": "working-plan",
}

#: The declaration kinds a prose locator may point inside. A guide's words
#: can be a declaration body in a ``.s0ma`` source rather than a file of
#: its own (C1's ``prose_locator``, B6 finding 2), and these are the two
#: declarations that hold documentation prose.
PROSE_FRAGMENT_KINDS: tuple[str, ...] = ("doc-guide", "doc-ref")

#: The anti-vacuity floor for this provider, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. An honest
#: minimum rather than a pin: the corpus is 169 documents today and a floor
#: at the count would turn the suite red the moment somebody writes the
#: next one. What this catches is the failure that matters — the file moved,
#: or the loader has stopped seeing it.
CATALOG_FLOORS: Mapping[tuple[str, str], int] = {(PROVIDER_ID, "documents"): 150}


class DocsCatalogError(DocsProviderError):
    """The catalog file does not satisfy the catalog schema.

    Raised rather than reported, for the reason
    :class:`~s0ma_dsl.docs_model.providers.DocsProviderError` exists: a
    file whose shape is wrong yields no records at all, so continuing
    would mean composing a bundle with no catalog in it and no sign that
    anything was missing. Every message names the JSON path of the value
    that is wrong.
    """


# ---------------------------------------------------------------------------
# Diagnostic names
# ---------------------------------------------------------------------------

#: A tracked Markdown file the catalog does not carry a row for (arch §11).
DOC_DOCUMENT_UNCATALOGED = "DOC_DOCUMENT_UNCATALOGED"

#: More than one row claims one canonical source (arch §11).
DOC_CANONICAL_DUPLICATE = "DOC_CANONICAL_DUPLICATE"

#: A reference is well formed and names nothing this build knows about.
#: Minted at B6 and used unchanged here for the one reference C2's
#: resolver cannot see: ``DocumentRecord.authority`` did not exist when
#: :func:`~s0ma_dsl.docs_model.validate.references` was written, so this
#: module resolves its own new field rather than leaving it unchecked.
DOC_TOPIC_UNRESOLVED = "DOC_TOPIC_UNRESOLVED"


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


def _digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    The same computation C4 and C5a make, so that three providers reading
    one file agree about what it hashes to.
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
        raise DocsCatalogError(f"{where}: expected an object, got {_named(value)}")
    return value


def _array(value: Any, where: str) -> list[Any]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise DocsCatalogError(f"{where}: expected a list, got {_named(value)}")
    return value


def _text(value: Any, where: str) -> str:
    """``value`` as a non-empty string, refusing anything else by name."""
    if not isinstance(value, str):
        raise DocsCatalogError(f"{where}: expected text, got {_named(value)}")
    if not value.strip():
        raise DocsCatalogError(
            f"{where}: is empty. An empty field is not the same as an absent "
            f"one, and this model has nowhere to put an unwritten fact."
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
        raise DocsCatalogError(
            f"{where}: does not match the {CATALOG_SCHEMA} shape "
            f"(unexpected: {unknown}, absent: {missing})"
        )


def _one_of(value: str, allowed: Sequence[str], noun: str, where: str) -> str:
    """``value``, refusing anything outside a closed vocabulary."""
    if value not in allowed:
        raise DocsCatalogError(
            f"{where}: {value!r} is not {noun}. The vocabulary is closed: "
            f"{', '.join(allowed)}."
        )
    return value


def _read_status(item: Mapping[str, Any], identifier: str, where: str) -> str:
    """A row's status, which its id has to agree with.

    The agreement is what makes a ``doc:`` id a claim rather than a
    label. Written once and called from both readings, so the catalog's
    own row is held to the same rule as every row it holds.
    """
    status = _one_of(
        _text(item["status"], f"{where}/status"),
        STATUSES,
        "a catalog status",
        f"{where}/status",
    )
    category = identifier.partition(":")[2].partition("/")[0]
    expected = STATUS_BY_CATEGORY[category]
    if status != expected:
        raise DocsCatalogError(
            f"{where}/status: {identifier} is filed under {category!r}, which "
            f"asserts the status {expected!r}, and the row says {status!r}. "
            f"One of the two is wrong and the file cannot say which — change "
            f"the id or change the status."
        )
    return status


def _sorted_unique(values: Sequence[str], noun: str, where: str) -> tuple[str, ...]:
    """A list that is sorted and says nothing twice, or a refusal.

    Sorted lists are what make two readings of one file byte-identical,
    and a repeated entry is either a mistake or a claim made twice.
    """
    if list(values) != sorted(values):
        raise DocsCatalogError(
            f"{where}: {noun} are not sorted. Sorted lists are what make two "
            f"readings of this file byte-identical."
        )
    repeated = sorted({item for item in values if values.count(item) > 1})
    if repeated:
        raise DocsCatalogError(f"{where}: {noun} repeat {repeated}")
    return tuple(values)


# ---------------------------------------------------------------------------
# What one reading produced
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Exclusion:
    """One tracked Markdown file the catalog deliberately does not carry.

    The completeness gate needs somewhere honest to put "this is not a
    document". A silent omission and a reasoned exclusion look identical
    from outside, so the file writes the reason down and the gate reads
    it — which is also what makes an exclusion reviewable.
    """

    path: str
    reason: str


@dataclass(frozen=True)
class CatalogRow:
    """One row's reader-facing facts, which the record type does not carry.

    ``kind``, ``status`` and ``audiences`` are catalog facts (arch §6.5)
    that ``@1``'s :class:`~s0ma_dsl.docs_model.records.DocumentRecord`
    deliberately does not declare — B4 deferred them because no gate
    branched on them, and C1 kept the deferral. F2 is the first caller
    that needs them: arch §9.1's navigation groups documents by what they
    are and who they are for, so a map of record with no audience column
    is a map that cannot say who a document is written for.

    They are exposed as a *view* rather than folded into the record for
    the reason this module's docstring gives: the file is richer than the
    record, and the projection is this module's job. Nothing composes a
    :class:`CatalogRow`, nothing hashes one, and no snapshot carries one —
    it is the same reading, answering a presentation question the model
    does not answer.
    """

    id: str
    kind: str
    status: str
    audiences: tuple[str, ...]


@dataclass(frozen=True)
class _Loaded:
    """One reading of the catalog file, cached so it happens once."""

    records: tuple[SourcedRecord, ...]
    documents: tuple[DocumentRecord, ...]
    rows: tuple[CatalogRow, ...]
    findings: tuple[Finding, ...]
    exclusions: tuple[Exclusion, ...]


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogProvider:
    """The document catalog of one checkout, read as records.

    ``root`` is the repository and ``relative`` is the catalog inside it.
    Both are fixed when the provider is built and neither is re-resolved
    at call time, which is what the provider contract asks for and what
    makes two calls in one process provably equal.
    """

    root: Path
    relative: str = CATALOG_FILE
    _cache: dict[str, _Loaded] = field(default_factory=dict, compare=False, repr=False)

    @property
    def provider_id(self) -> str:
        """This adapter's stable id."""
        return PROVIDER_ID

    # -- the public reading ------------------------------------------------

    def provide(self) -> ProviderResult:
        """Every catalog row, and the catalog's own row, sorted."""
        return ProviderResult(
            provider_id=self.provider_id, records=sort_records(self._load().records)
        )

    def findings(self) -> tuple[Finding, ...]:
        """What is wrong with the catalog's content, in reporting order.

        Separate from :meth:`provide` because the provider contract has
        nowhere to put a finding: a result is records. Completeness is
        *not* here — it needs the corpus, which this provider does not
        read; see :func:`check_completeness`.
        """
        return self._load().findings

    def documents(self) -> tuple[DocumentRecord, ...]:
        """Every row as a record, in id order, without the provenance."""
        return self._load().documents

    def rows(self) -> tuple[CatalogRow, ...]:
        """Every row's presentation facts, in id order (:class:`CatalogRow`).

        One entry per entry of :meth:`documents`, keyed by the same id, so
        a caller that needs both joins them on the id rather than reading
        the file a second time. A second reading is how a page ends up
        describing a catalog nobody composed.
        """
        return self._load().rows

    def exclusions(self) -> tuple[Exclusion, ...]:
        """Every tracked file the catalog excludes, with its reason."""
        return self._load().exclusions

    def cataloged_paths(self) -> frozenset[str]:
        """Every path the catalog accounts for: a row's source or excluded."""
        return frozenset(
            [record.canonical_source for record in self._load().documents]
            + [item.path for item in self._load().exclusions]
        )

    # -- reading -----------------------------------------------------------

    def _load(self) -> _Loaded:
        """Read the file once and remember it."""
        held = self._cache.get(self.relative)
        if held is None:
            held = self._read()
            self._cache[self.relative] = held
        return held

    def _read(self) -> _Loaded:
        """The whole reading: shape, rows, the self row, the gates."""
        path = self.root / self.relative
        if not path.is_file():
            raise DocsCatalogError(
                f"{self.relative} is not a file in this checkout. The catalog "
                f"is the authored source of every document record; without it "
                f"there is nothing to describe the documentation with."
            )
        text = path.read_text(encoding="utf-8")
        try:
            document = json.loads(text)
        except json.JSONDecodeError as broken:
            raise DocsCatalogError(
                f"{self.relative}: is not readable as JSON ({broken.msg} at "
                f"line {broken.lineno}, column {broken.colno})"
            ) from broken

        raw = _object(document, self.relative)
        _exactly(raw, ("documents", "excluded", "schema", "self"), self.relative)
        schema = _text(raw["schema"], f"{self.relative}#/schema")
        if schema != CATALOG_SCHEMA:
            raise DocsCatalogError(
                f"{self.relative}#/schema: this loader reads "
                f"{CATALOG_SCHEMA!r}; the file names {schema!r}"
            )

        exclusions = self._read_exclusions(raw["excluded"])
        excluded = frozenset(item.path for item in exclusions)
        rows, facts = self._read_documents(raw["documents"], excluded)
        own, own_facts = self._read_self(raw["self"])
        if any(record.id == own.id for record in rows):
            raise DocsCatalogError(
                f"{self.relative}#/self: {own.id} is also an ordinary row. The "
                f"catalog's row for itself is synthesized, so writing it out a "
                f"second time produces two records under one id."
            )
        documents = (*rows, own)

        stamp = Provenance(
            adapter_id=self.provider_id,
            schema_version=SCHEMA,
            source=self.relative,
            source_sha256=_digest_of(text),
        )
        records = tuple(
            SourcedRecord(record=record, provenance=stamp) for record in documents
        )
        ordered = tuple(sorted(documents, key=lambda record: record.id))
        return _Loaded(
            records=records,
            documents=ordered,
            rows=tuple(sorted((*facts, own_facts), key=lambda row: row.id)),
            findings=sort_findings(check_canonical_sources(ordered)),
            exclusions=exclusions,
        )

    # -- the exclusions ----------------------------------------------------

    def _read_exclusions(self, raw: Any) -> tuple[Exclusion, ...]:
        """Every recorded exclusion, each naming a file that is really there."""
        entries = _array(raw, f"{self.relative}#/excluded")
        found: list[Exclusion] = []
        for index, entry in enumerate(entries):
            where = f"{self.relative}#/excluded/{index}"
            item = _object(entry, where)
            _exactly(item, ("path", "reason"), where)
            path = self._checked_path(_text(item["path"], f"{where}/path"), f"{where}/path")
            found.append(Exclusion(path=path, reason=_text(item["reason"], f"{where}/reason")))
        paths = [item.path for item in found]
        _sorted_unique(paths, "exclusions", f"{self.relative}#/excluded")
        return tuple(found)

    # -- the rows ----------------------------------------------------------

    def _read_documents(
        self, raw: Any, excluded: frozenset[str]
    ) -> tuple[tuple[DocumentRecord, ...], tuple[CatalogRow, ...]]:
        """Every row as a record and as a view, in the file's own order."""
        entries = _array(raw, f"{self.relative}#/documents")
        if not entries:
            raise DocsCatalogError(
                f"{self.relative}#/documents: is empty. An empty catalog "
                f"passes every gate that reads it and describes nothing, "
                f"which is the failure the anti-vacuity floor exists for."
            )
        found: list[DocumentRecord] = []
        facts: list[CatalogRow] = []
        for index, entry in enumerate(entries):
            record, row = self._read_document(
                entry, f"{self.relative}#/documents/{index}"
            )
            found.append(record)
            facts.append(row)
        identifiers = [record.id for record in found]
        _sorted_unique(identifiers, "row ids", f"{self.relative}#/documents")
        for record in found:
            if record.canonical_source in excluded:
                raise DocsCatalogError(
                    f"{self.relative}: {record.canonical_source} is both "
                    f"cataloged as {record.id} and listed as excluded. A file "
                    f"is a document or it is not; the completeness gate reads "
                    f"both lists and cannot be told two things."
                )
        return tuple(found), tuple(facts)

    def _read_document(
        self, entry: Any, where: str
    ) -> tuple[DocumentRecord, CatalogRow]:
        """One row, checked field by field against what it claims to be."""
        item = _object(entry, where)
        _exactly(
            item,
            (
                "audiences",
                "authority",
                "canonical_source",
                "covers",
                "governed_by",
                "id",
                "kind",
                "prose_locator",
                "status",
                "title",
            ),
            where,
        )
        identifier = self._read_id(item, where)
        status = _read_status(item, identifier, where)
        kind = _one_of(
            _text(item["kind"], f"{where}/kind"), KINDS, "a document kind", f"{where}/kind"
        )
        audiences = _sorted_unique(
            [
                _one_of(
                    _text(value, f"{where}/audiences/{position}"),
                    AUDIENCES,
                    "an audience",
                    f"{where}/audiences/{position}",
                )
                for position, value in enumerate(_array(item["audiences"], f"{where}/audiences"))
            ],
            "audiences",
            f"{where}/audiences",
        )
        if not audiences:
            raise DocsCatalogError(
                f"{where}/audiences: is empty. A document nobody is written "
                f"for cannot be placed in any presentation, and arch §9.1's "
                f"navigation is audience-filtered."
            )
        source = self._checked_path(
            _text(item["canonical_source"], f"{where}/canonical_source"),
            f"{where}/canonical_source",
        )
        record = DocumentRecord(
            id=identifier,
            title=_text(item["title"], f"{where}/title"),
            canonical_source=source,
            prose_locator=self._read_prose_locator(
                item["prose_locator"], f"{where}/prose_locator"
            ),
            governed_by=self._read_ids(item["governed_by"], f"{where}/governed_by"),
            covers=self._read_ids(item["covers"], f"{where}/covers"),
            authority=self._read_authority(item["authority"], f"{where}/authority"),
        )
        return record, CatalogRow(
            id=identifier, kind=kind, status=status, audiences=audiences
        )

    def _read_id(self, item: Mapping[str, Any], where: str) -> str:
        """A row's id, refusing anything but a normalized ``doc:`` form."""
        identifier = _text(item["id"], f"{where}/id")
        if id_form(identifier) != "doc":
            raise DocsCatalogError(
                f"{where}/id: {identifier!r} is not a document id. A catalog "
                f"row is addressed as doc:<category>/<slug>, where the "
                f"category is one of: {', '.join(sorted(STATUS_BY_CATEGORY))}."
            )
        if normalize_id(identifier) != identifier:
            raise DocsCatalogError(
                f"{where}/id: {identifier!r} is not the comparable form of "
                f"that id; identity comparisons run on the normalized form"
            )
        category = identifier.partition(":")[2].partition("/")[0]
        if category not in STATUS_BY_CATEGORY:
            raise DocsCatalogError(
                f"{where}/id: {category!r} is not a catalog category. The "
                f"categories are closed, because each one asserts a status: "
                f"{', '.join(sorted(STATUS_BY_CATEGORY))}."
            )
        return identifier

    def _read_authority(self, raw: Any, where: str) -> str:
        """The authority this document *is*, or empty where it is none.

        The field re-added at this milestone (B4 deferred row 10, arch
        §6.5: "AuthorityRef when normative, otherwise evidence class"). It
        is the document's own identity as a written authority — the ADR
        file *is* ``authority:adr/repo.ADR-012`` — and it is deliberately
        not ``governed_by``, which says what governs the document instead.
        Most documents are not an authority, and empty is the honest
        answer for them.
        """
        if not isinstance(raw, str):
            raise DocsCatalogError(f"{where}: expected text, got {_named(raw)}")
        if not raw:
            return ""
        if id_form(raw) != "authority":
            raise DocsCatalogError(
                f"{where}: {raw!r} is not an authority id. A document that is "
                f"itself a written authority names the id the repository "
                f"provider emits for it — authority:<class>/<stable-name> — "
                f"and a document that is not one leaves this empty."
            )
        return raw

    def _read_prose_locator(self, raw: Any, where: str) -> str:
        """Where the words are, which is not always the file they are about.

        ``<path>`` names a whole file; ``<path>#doc-guide:<name>`` names
        one declaration body inside a ``.s0ma`` source. A mirror points at
        the document it copies and a generated page points at the
        declaration it was rendered from, because those are the places an
        author may actually edit — a finding about a generated page's
        prose that pointed at the generated page would be telling somebody
        to edit a file the build overwrites.
        """
        value = _text(raw, where)
        path, separator, fragment = value.partition("#")
        self._checked_path(path, where)
        if not separator:
            return value
        kind, colon, name = fragment.partition(":")
        if kind not in PROSE_FRAGMENT_KINDS or not colon or not name:
            raise DocsCatalogError(
                f"{where}: {fragment!r} is not a declaration reference. Write "
                f"<path>#<kind>:<name>, where the kind is one of: "
                f"{', '.join(PROSE_FRAGMENT_KINDS)}."
            )
        return value

    def _read_ids(self, raw: Any, where: str) -> tuple[str, ...]:
        """A sorted list of ids, each one a form the model addresses."""
        values: list[str] = []
        for index, entry in enumerate(_array(raw, where)):
            identifier = _text(entry, f"{where}/{index}")
            validate_id(identifier)
            if normalize_id(identifier) != identifier:
                raise DocsCatalogError(
                    f"{where}/{index}: {identifier!r} is not the comparable "
                    f"form of that id"
                )
            values.append(identifier)
        return _sorted_unique(values, "ids", where)

    def _checked_path(self, value: str, where: str) -> str:
        """A repository-relative path that names a file that is really there."""
        if value.startswith("/") or "\\" in value:
            raise DocsCatalogError(
                f"{where}: {value!r} is not a repository-relative POSIX path. "
                f"A machine path in a record makes the build's output depend "
                f"on the machine that ran it (INV-5)."
            )
        if not (self.root / value).is_file():
            raise DocsCatalogError(
                f"{where}: {value} is not a file in this checkout. A catalog "
                f"row that names a file nobody can open describes nothing."
            )
        return value

    # -- the catalog's own row ---------------------------------------------

    def _read_self(self, raw: Any) -> tuple[DocumentRecord, CatalogRow]:
        """The catalog's row for itself, from the identity it declares.

        Synthesized rather than written as an ordinary row, so that the
        one document guaranteed to be in the catalog is the catalog. Its
        reader-facing facts are still authored — a row nobody can retitle
        is a row nobody owns — but its source, its locator and its empty
        coverage are this provider's, because they are facts about the
        file it just read.
        """
        where = f"{self.relative}#/self"
        item = _object(raw, where)
        _exactly(item, ("audiences", "id", "kind", "status", "title"), where)
        identifier = self._read_id(item, where)
        status = _read_status(item, identifier, where)
        kind = _one_of(
            _text(item["kind"], f"{where}/kind"), KINDS, "a document kind", f"{where}/kind"
        )
        audiences = _sorted_unique(
            [
                _one_of(
                    _text(value, f"{where}/audiences/{position}"),
                    AUDIENCES,
                    "an audience",
                    f"{where}/audiences/{position}",
                )
                for position, value in enumerate(_array(item["audiences"], f"{where}/audiences"))
            ],
            "audiences",
            f"{where}/audiences",
        )
        return DocumentRecord(
            id=identifier,
            title=_text(item["title"], f"{where}/title"),
            canonical_source=self.relative,
            prose_locator=self.relative,
            governed_by=(),
            covers=(),
            authority="",
        ), CatalogRow(id=identifier, kind=kind, status=status, audiences=audiences)


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def tracked_markdown(root: Path) -> tuple[str, ...]:
    """Every Markdown file git tracks, repository-relative and sorted.

    The same question the A6 guard asks, asked the same way, because the
    two have to agree until F2 retires that guard under plan §10.3's
    equivalence rule. It lives outside the provider on purpose: a
    provider is a reading of a source, and running a process is not one.

    Raises rather than returning empty where git cannot answer. A corpus
    that resolves empty would make the completeness gate pass everything,
    which is the exact failure ``DOC_GATE_VACUOUS`` exists to name.
    """
    if shutil.which("git") is None:
        raise DocsCatalogError(
            "git is not on PATH, so the tracked corpus cannot be enumerated. "
            "The completeness gate compares the catalog against what the "
            "repository tracks; without that list it would pass vacuously."
        )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, repo-local
        ["git", "-C", str(root), "ls-files", "*.md"],  # noqa: S607
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise DocsCatalogError(
            f"git ls-files failed in {root}: {result.stderr.strip()}. The "
            f"completeness gate needs the tracked corpus and will not guess it."
        )
    found = tuple(sorted(line for line in result.stdout.splitlines() if line))
    if not found:
        raise DocsCatalogError(
            f"{root} tracks no Markdown files at all. An empty corpus is not "
            f"an answer this gate can use — it would report nothing missing "
            f"from any catalog, however empty."
        )
    return found


def check_completeness(catalog: CatalogProvider, tracked: Iterable[str]) -> list[Finding]:
    """Every tracked document has a row, or says why it has none.

    ``DOC_DOCUMENT_UNCATALOGED``. The corpus is passed in rather than
    read here, so the gate can be run against a fixture tree as easily as
    against the repository — and so that the one call that shells out to
    git is visible at the call site.
    """
    accounted = catalog.cataloged_paths()
    findings: list[Finding] = []
    for path in sorted(set(tracked) - accounted):
        findings.append(
            Finding(
                code=DOC_DOCUMENT_UNCATALOGED,
                location=path,
                message=f"{path} is tracked documentation and the catalog has no row for it",
                remediation=(
                    f"Add a row to {catalog.relative} naming this file as its "
                    f"canonical source, or — if it is not documentation — add "
                    f"it to that file's excluded list with the reason it is "
                    f"not. A silent omission and a reasoned exclusion look "
                    f"the same from outside; only one of them is reviewable."
                ),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Gates over the composed catalog
# ---------------------------------------------------------------------------


def check_canonical_sources(documents: Sequence[DocumentRecord]) -> list[Finding]:
    """No file is the canonical source of two documents.

    ``DOC_CANONICAL_DUPLICATE``. Two rows over one file are two answers
    to "what is this document", and every reader-facing surface that
    groups by document would show it twice under two names.

    Takes records rather than a bundle so the same rule can be run over
    one provider's rows and over a whole composition — the second reading
    is the one that catches a *derived* catalog row colliding with an
    authored one, which is how the core provider's registered
    documentation declarations will meet this file.
    """
    by_source: dict[str, list[str]] = {}
    for record in documents:
        by_source.setdefault(record.canonical_source, []).append(record.id)
    findings: list[Finding] = []
    for source, identifiers in sorted(by_source.items()):
        if len(identifiers) < 2:
            continue
        named = ", ".join(sorted(identifiers))
        findings.append(
            Finding(
                code=DOC_CANONICAL_DUPLICATE,
                location=source,
                message=f"{source} is the canonical source of {len(identifiers)} rows: {named}",
                remediation=(
                    "One file, one document. Keep the row that names what the "
                    "file is and delete the other, or give the second row its "
                    "own source — two rows over one file make every "
                    "document-grouped surface show it twice."
                ),
            )
        )
    return findings


def check_document_authorities(bundle: DocsBundle) -> list[Finding]:
    """Every ``authority`` a catalog row claims is an authority that exists.

    ``DOC_TOPIC_UNRESOLVED``. C2's reference resolver walks the edges
    ``@1`` declared when it was written, and ``DocumentRecord.authority``
    arrived after it; rather than leave the new field the one unchecked
    reference in the model, the milestone that added it resolves it. When
    :func:`~s0ma_dsl.docs_model.validate.references` learns the field this
    function becomes redundant and should go.
    """
    known = {record.id for record in bundle.authorities}
    findings: list[Finding] = []
    for record in sorted(bundle.documents, key=lambda item: item.id):
        if not record.authority or record.authority in known:
            continue
        findings.append(
            Finding(
                code=DOC_TOPIC_UNRESOLVED,
                location=record.canonical_source,
                message=(
                    f"{record.id} claims to be {record.authority}, which no "
                    f"provider in this build emits"
                ),
                remediation=(
                    "Either the authority index has stopped indexing this "
                    "document — check the repository provider — or the id is "
                    "written wrongly. A document that claims an authority "
                    "nobody knows about is citable by nothing."
                ),
            )
        )
    return findings
