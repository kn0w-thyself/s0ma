"""Authored teaching knowledge, read from a file a person wrote.

Milestone C5a of the docs-function plan (internal) §8, and the loader C5b
reuses unchanged: it is parameterized by a data-file path and the domain
that file is expected to declare, so the language concepts and the product
concepts are two configurations of one provider rather than two providers
that will drift apart.

**Why the teaching content is data and not a declaration.** D-4 is a strict
no-new-DSL ruling. A concept is therefore a row in a JSON file, loaded here,
validated here, and turned into records here — no grammar changes, no
parser changes, nothing new for an author to learn beyond the shape of the
file itself. The file is the authored source; this module is the reading of
it.

**What this provider emits, and what it deliberately leaves to C4.** Two
groups. The concepts themselves, and the ``authority:spec/<slug>`` records
those concepts cite — because C4 indexes the current specification as one
record, ``authority:spec/current``, and a concept needs to cite the
*section* that defines it. The two providers never claim the same id, so
they merge without a word between them. C4 stays the authority on the
document's identity; this provider adds the sections its own concepts point
at, and nothing else.

**One provenance source per record: the authored file.** Every record this
provider emits — a concept and an authority alike — is stamped with the
concepts file it was read from. That is the file a person opens to change
anything here, including which section an authority points at, so it is the
honest answer to "where did this come from". The cited document's identity
is carried where it belongs: in ``AuthorityRef.source`` and
``AuthorityRef.content_sha256``, which are the specification's, not the
concepts file's.

**Where a section anchor is checked.** The authored file records a section
*number* and the heading it should resolve to. Numbers are what other
documents cite and they move only on a restructure; wording is reworded
freely. So the number is the anchor, the heading is the check, and a number
that resolves to no heading — or to two — is refused rather than guessed
at, which is the discipline B4 arrived at and proved.

**Refusal versus finding.** The line is the shape of the file against the
truth of its content:

* a file that does not satisfy its own schema — a missing key, an id that
  matches no form, a relation word outside the vocabulary, a citation of
  an authority the file neither declares nor lists as another provider's —
  raises :class:`DocsConceptsError`, naming the JSON path of the offending
  value. Nothing can be built from it, so nothing is;
* something wrong with the *content* — a pinned digest the cited document
  has moved past, a one-sided symmetric relation, a word the product voice
  does not use — is a :class:`~s0ma_dsl.docs_model.providers.Finding`,
  collected so an author sees every one of them in a single run.

**Nothing here writes, and nothing here opens a socket.** Every path is
repository-relative POSIX (INV-5), and every digest is over LF-normalized
UTF-8, so a record carries no trace of the machine that built it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.ids import AliasIndex, id_form, normalize_id, validate_id
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
    AuthorityRef,
    ConceptRecord,
    DocsBundle,
    ExampleRef,
    Provenance,
    authored_prose_fields,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

__all__ = [
    "CONCEPTS_DIR",
    "CONCEPTS_SCHEMA",
    "DOC_AUTHORITY_STALE",
    "DOC_RELATION_ONE_SIDED",
    "DOC_VOICE_VIOLATION",
    "FORBIDDEN_IN_AUTHORED_PROSE",
    "LANGUAGE_CONCEPTS",
    "LANGUAGE_DOMAIN",
    "LANGUAGE_FLOORS",
    "MINTED_CODES",
    "RELATIONS",
    "RELATION_NAMES",
    "SYMMETRIC_RELATIONS",
    "ConceptsProvider",
    "DocsConceptsError",
    "Relation",
    "check_concept_relations",
    "check_voice",
    "headings_by_number",
    "relation_of",
]

#: The authored file's own schema. Not the model's: a concepts file is an
#: input to the documentation model, not a serialization of it, and giving
#: the two one version string would make a change to either look like a
#: change to both.
CONCEPTS_SCHEMA = "s0ma-docs-concepts@1"

#: Where authored concept files live, repository-relative (ADR-012).
CONCEPTS_DIR = "docs/s0ma_src/concepts"

#: The language domain and its file: the eleven declaration kinds and the
#: vocabulary a person needs to read one. C5b adds the product domain
#: alongside it, through this same loader.
LANGUAGE_DOMAIN = "language"
LANGUAGE_CONCEPTS = f"{CONCEPTS_DIR}/{LANGUAGE_DOMAIN}.json"

#: Anti-vacuity floors for the language file, in the shape
#: :func:`~s0ma_dsl.docs_model.validate.check_floors` reads. Honest
#: minimums rather than pins: twenty-five concepts and thirty section
#: anchors are authored today, and a floor at the count would turn the
#: suite red the moment somebody writes a twenty-sixth. What these catch is
#: the failure that matters — a file that moved, or a loader that has
#: stopped seeing it.
LANGUAGE_FLOORS: Mapping[tuple[str, str], int] = {
    (f"concepts-{LANGUAGE_DOMAIN}", "concepts"): 20,
    (f"concepts-{LANGUAGE_DOMAIN}", "authorities"): 20,
}


class DocsConceptsError(DocsProviderError):
    """An authored concepts file does not satisfy the concepts schema.

    Raised rather than reported, for the reason
    :class:`~s0ma_dsl.docs_model.providers.DocsProviderError` exists: a
    file whose shape is wrong yields no records at all, so continuing
    would mean composing a bundle that is silently missing a domain.
    Every message names the JSON path of the value that is wrong.
    """


# ---------------------------------------------------------------------------
# Diagnostic names
# ---------------------------------------------------------------------------

#: A concepts file pins the digest of a document it cites, and the document
#: has changed since. **Minted at C5a.**
DOC_AUTHORITY_STALE = "DOC_AUTHORITY_STALE"

#: One concept declares a symmetric relation to another and the other does
#: not declare it back. **Minted at C5a.**
DOC_RELATION_ONE_SIDED = "DOC_RELATION_ONE_SIDED"

#: Authored teaching prose uses a word the product voice does not use.
#: **Minted at C5a.**
DOC_VOICE_VIOLATION = "DOC_VOICE_VIOLATION"

#: Codes this milestone uses that the architecture plan's §11 table does
#: not name, with where each came from. The same discipline C2 applied to
#: its three: needed, used, and not silently added to a frozen namespace.
MINTED_CODES: Mapping[str, str] = {
    DOC_AUTHORITY_STALE: (
        "C5a. A concept cites a section of a document and pins that "
        "document's digest, so the citation can be re-verified rather than "
        "trusted. §11's DOC_VERSION_MISMATCH is about a document that "
        "represents another release; this is about a pin an author has to "
        "re-read, which is a different question with a different fix."
    ),
    DOC_RELATION_ONE_SIDED: (
        "C5a. The concept-to-concept edge arrived with "
        "ConceptRecord.related_concepts, and a symmetric relation declared "
        "on one side only makes the reverse query arch §6.7 asks for "
        "answer differently depending on which end you start from. §11 has "
        "no row for an edge that resolves and is still wrong."
    ),
    DOC_VOICE_VIOLATION: (
        "C5a. B4 proved the voice rule can only reach authored prose and "
        "never a quotation (finding 4); C1 built FIELD_CLASS so a gate "
        "could tell the two apart. This is that gate, and §11 is a table "
        "of resolution and currency failures with no row for wording."
    ),
}

#: What must never appear in authored, user-facing prose: the word this
#: product does not use for feedback data is the owner's standing call
#: (plan §3.1 rule 10), and the letter-o spellings of the two product names
#: are INV-1 (rule 5). The two spellings are written with a one-character
#: class so this file's own source never contains a forbidden literal — the
#: same self-excluding trick ``scripts/check.py`` uses for its INV-1 guard.
#: The first pattern is spelled out, because a diagnostic that cannot name
#: the word it refuses leaves an author guessing.
FORBIDDEN_IN_AUTHORED_PROSE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("payload", re.compile(r"\bpayload\b", re.IGNORECASE)),
    ("the letter-o spelling of s0ma", re.compile(r"\bs[o]ma\b", re.IGNORECASE)),
    ("the letter-o spelling of studi0", re.compile(r"\bstudi[o]\b", re.IGNORECASE)),
)


# ---------------------------------------------------------------------------
# The relation vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Relation:
    """One kind of edge a concept may declare to another concept.

    Closed on purpose. An open vocabulary would let two authors write
    ``contrasts-with`` and ``contrasted-with`` for one idea, and a reverse
    query over the graph would then answer differently depending on which
    word a page happened to use.
    """

    name: str
    symmetric: bool
    note: str


#: Every relation a concept may declare, sorted by name.
RELATIONS: tuple[Relation, ...] = (
    Relation(
        "contrasts-with",
        True,
        "Two concepts a reader has to tell apart: a nerve and a cell, a "
        "test and an example. Symmetric — if one contrasts with the other, "
        "the other contrasts with it, and both records have to say so.",
    ),
    Relation(
        "part-of",
        False,
        "This concept is one component of a larger one: a declaration kind "
        "is part of what a source file contains. Not symmetric, and the "
        "reverse edge is deliberately not required — a whole with fifteen "
        "parts would carry fifteen edges nobody reads.",
    ),
    Relation(
        "requires",
        False,
        "You cannot write or understand this concept without the other "
        "one first: a nerve requires a layer, a contract, and an intent. "
        "This is the edge a teaching order is built from.",
    ),
)

#: The relation words, sorted, for validation and for reporting.
RELATION_NAMES: tuple[str, ...] = tuple(sorted(item.name for item in RELATIONS))

#: The relations that must be declared from both ends.
SYMMETRIC_RELATIONS: frozenset[str] = frozenset(
    item.name for item in RELATIONS if item.symmetric
)


def relation_of(name: str) -> Relation:
    """The relation ``name`` addresses, refusing a word outside the set."""
    for item in RELATIONS:
        if item.name == name:
            return item
    raise DocsConceptsError(
        f"{name!r} is not a relation a concept may declare. The vocabulary "
        f"is closed: {', '.join(RELATION_NAMES)}."
    )


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """One file, read once: where it is, what it says, what it hashes to."""

    path: str
    text: str
    digest: str


def _digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    The same computation C4 makes, and deliberately so: two digests of one
    file that differ in shape invite a false mismatch, and this module
    exists partly to compare its own pin against C4's world.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


#: Any Markdown heading, with its level, so a section can be found by the
#: number it opens with.
_HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")

#: The number a heading opens with: ``4``, ``4.1``, ``4.4a``, ``4.12.5``.
#: A trailing letter is a real form in this specification (§4.4a is the
#: helper declaration), and the trailing period is optional because the
#: top-level headings carry one and the nested ones do not.
_SECTION_NUMBER = re.compile(r"^(?P<number>[0-9]+[a-z]?(?:\.[0-9]+[a-z]?)*)\.?(?:\s|$)")


def headings_by_number(text: str) -> Mapping[str, tuple[str, ...]]:
    """Every numbered heading of a Markdown document, keyed by its number.

    The value is a tuple because ambiguity is the thing worth seeing: a
    number that opens two headings cannot anchor a citation, and this
    returns both so the refusal can name them.
    """
    found: dict[str, list[str]] = {}
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = _HEADING.match(line)
        if heading is None:
            continue
        title = heading.group("title")
        numbered = _SECTION_NUMBER.match(title)
        if numbered is None:
            continue
        found.setdefault(numbered.group("number"), []).append(title)
    return {number: tuple(titles) for number, titles in sorted(found.items())}


# ---------------------------------------------------------------------------
# Typed readers over untyped data
# ---------------------------------------------------------------------------


def _object(value: Any, where: str) -> dict[str, Any]:
    """``value`` as a JSON object, refusing anything else by name."""
    if not isinstance(value, dict):
        raise DocsConceptsError(f"{where}: expected an object, got {_named(value)}")
    return value


def _array(value: Any, where: str) -> list[Any]:
    """``value`` as a JSON array, refusing anything else by name."""
    if not isinstance(value, list):
        raise DocsConceptsError(f"{where}: expected a list, got {_named(value)}")
    return value


def _text(value: Any, where: str) -> str:
    """``value`` as a non-empty string, refusing anything else by name."""
    if not isinstance(value, str):
        raise DocsConceptsError(f"{where}: expected text, got {_named(value)}")
    if not value.strip():
        raise DocsConceptsError(
            f"{where}: is empty. An empty field is not the same as an absent "
            f"one, and this model has nowhere to put an unwritten fact."
        )
    return value


#: Anything that is not a letter or a digit, for slugging a term.
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """A term as the slug its id has to carry.

    Lowercase, and every run of anything else collapsed to one hyphen.
    ``.s0ma file`` slugs to ``s0ma-file`` and ``uses:`` to ``uses``, so a
    term may read the way a person says it while its id stays in the one
    form :data:`~s0ma_dsl.docs_model.ids.ID_FORMS` addresses concepts by.
    """
    return _NOT_SLUG.sub("-", text.lower()).strip("-")


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


def _exactly(raw: Mapping[str, Any], expected: Sequence[str], where: str) -> None:
    """Refuse an object that does not carry exactly the expected keys.

    An unknown key and a missing key are both errors, for C1's reason: a
    reader that tolerated a stray key would silently drop what an author
    wrote, and this whole model exists against that.
    """
    unknown = sorted(set(raw) - set(expected))
    missing = sorted(set(expected) - set(raw))
    if unknown or missing:
        raise DocsConceptsError(
            f"{where}: does not match the {CONCEPTS_SCHEMA} shape "
            f"(unexpected: {unknown}, absent: {missing})"
        )


# ---------------------------------------------------------------------------
# What one reading of a concepts file produced
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Loaded:
    """One reading of one concepts file, cached so it happens once."""

    records: tuple[SourcedRecord, ...]
    findings: tuple[Finding, ...]
    aliases: AliasIndex
    external_ids: tuple[str, ...]


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptsProvider:
    """One authored concepts file, read as records.

    ``root`` is the repository the file lives in, ``relative`` is the file,
    and ``domain`` is what that file must declare itself to be. All three
    are fixed when the provider is built and none is re-resolved at call
    time, which is what the provider contract asks for and what makes two
    calls in one process provably equal.

    The domain is a parameter rather than a constant because C5b reads a
    second file through this same class. Requiring the file to *declare*
    its domain, and refusing it when the two disagree, is what stops a
    provider being pointed at the wrong file and quietly succeeding.
    """

    root: Path
    relative: str
    domain: str
    _cache: dict[str, _Loaded] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def language(cls, root: Path) -> ConceptsProvider:
        """The language-concepts provider for a checkout at ``root``."""
        return cls(root=root, relative=LANGUAGE_CONCEPTS, domain=LANGUAGE_DOMAIN)

    @property
    def provider_id(self) -> str:
        """This adapter's stable id: one per domain, never one per file."""
        return f"concepts-{self.domain}"

    # -- the public reading ------------------------------------------------

    def provide(self) -> ProviderResult:
        """The file's concepts and the section anchors they cite, sorted."""
        return ProviderResult(
            provider_id=self.provider_id, records=sort_records(self._load().records)
        )

    def findings(self) -> tuple[Finding, ...]:
        """What is wrong with the file's content, in reporting order.

        Separate from :meth:`provide` because the provider contract has
        nowhere to put a finding: a result is records. These are the
        problems an author fixes — a stale pin, a one-sided relation, a
        word the voice does not use — and none of them stops the records
        from being produced.
        """
        return self._load().findings

    def alias_index(self) -> AliasIndex:
        """The alternate terms this file declares, as a resolution index.

        No record type carries an alias field in ``@1`` — C1 defers that to
        F6 — so the authored aliases land here instead, in exactly the
        helper C1 built for them to land in. Nothing is lost and no
        deferral is jumped.
        """
        return self._load().aliases

    def external_ids(self) -> tuple[str, ...]:
        """Ids this file cites that another provider is expected to emit.

        The seam C2 built for a target that is real and lives outside the
        reading that names it. Written down in the file rather than
        inferred, so a citation of something nobody produces is a mistake
        the loader can see rather than a silence.
        """
        return self._load().external_ids

    # -- reading -----------------------------------------------------------

    def _source(self, relative: str, where: str) -> _Source:
        """One file of the checkout, refusing an absent one by name."""
        path = self.root / relative
        if not path.is_file():
            raise DocsConceptsError(
                f"{where}: {relative} is not a file in this checkout. A "
                f"concepts file names the documents its concepts are "
                f"governed by, repository-relative; a name nothing answers "
                f"to cannot be hashed or read."
            )
        text = path.read_text(encoding="utf-8")
        return _Source(path=relative, text=text, digest=_digest_of(text))

    def _load(self) -> _Loaded:
        """Read the file once and remember it."""
        held = self._cache.get(self.relative)
        if held is None:
            held = self._read()
            self._cache[self.relative] = held
        return held

    def _read(self) -> _Loaded:
        """The whole reading: shape, anchors, records, gates."""
        own = self._source(self.relative, "the concepts file")
        try:
            document = json.loads(own.text)
        except json.JSONDecodeError as broken:
            raise DocsConceptsError(
                f"{own.path}: is not readable as JSON ({broken.msg} at line "
                f"{broken.lineno}, column {broken.colno})"
            ) from broken

        raw = _object(document, own.path)
        _exactly(
            raw,
            ("aliases", "authorities", "domain", "external_ids", "records", "schema", "sources"),
            own.path,
        )
        self._check_identity(raw, own)

        sources = self._read_sources(raw["sources"], own)
        findings: list[Finding] = []
        authorities = self._read_authorities(raw["authorities"], sources, own, findings)
        external_ids = self._read_external_ids(raw["external_ids"], own)
        concepts = self._read_concepts(
            raw["records"], own, frozenset(authorities), external_ids
        )
        aliases = self._read_aliases(raw["aliases"], own, frozenset(concepts), external_ids)

        stamp = _stamp(self.provider_id, own)
        records: list[SourcedRecord] = [
            SourcedRecord(record=authority, provenance=stamp)
            for authority in authorities.values()
        ]
        records.extend(
            SourcedRecord(record=concept, provenance=stamp) for concept in concepts.values()
        )
        for index, concept_id in enumerate(sorted(concepts)):
            findings.extend(
                check_voice(concepts[concept_id], f"{own.path}#/records/{index}")
            )
        findings.extend(
            _one_sided_findings(tuple(concepts.values()), own.path, external_ids)
        )
        return _Loaded(
            records=tuple(records),
            findings=sort_findings(findings),
            aliases=aliases,
            external_ids=external_ids,
        )

    # -- the file's own identity -------------------------------------------

    def _check_identity(self, raw: Mapping[str, Any], own: _Source) -> None:
        """The file says what it is, and what it says has to be true."""
        schema = _text(raw["schema"], f"{own.path}#/schema")
        if schema != CONCEPTS_SCHEMA:
            raise DocsConceptsError(
                f"{own.path}#/schema: this loader reads {CONCEPTS_SCHEMA!r}; "
                f"the file names {schema!r}"
            )
        domain = _text(raw["domain"], f"{own.path}#/domain")
        if domain != self.domain:
            raise DocsConceptsError(
                f"{own.path}#/domain: the provider was built for the "
                f"{self.domain!r} domain and this file declares {domain!r}. "
                f"One file, one domain — the provider id is derived from it, "
                f"and two domains under one id would make the merge rule's "
                f"survivor depend on which file ran first."
            )

    # -- the documents the anchors point into ------------------------------

    def _read_sources(self, raw: Any, own: _Source) -> dict[str, tuple[_Source, str]]:
        """Every cited document, read live, paired with its pinned digest."""
        entries = _array(raw, f"{own.path}#/sources")
        if not entries:
            raise DocsConceptsError(
                f"{own.path}#/sources: is empty. Every concept cites the "
                f"document that defines it, and a document nobody named "
                f"cannot be hashed."
            )
        found: dict[str, tuple[_Source, str]] = {}
        for index, entry in enumerate(entries):
            where = f"{own.path}#/sources/{index}"
            item = _object(entry, where)
            _exactly(item, ("path", "sha256"), where)
            path = _text(item["path"], f"{where}/path")
            pinned = _text(item["sha256"], f"{where}/sha256")
            if not re.fullmatch(r"[0-9a-f]{64}", pinned):
                raise DocsConceptsError(
                    f"{where}/sha256: {pinned!r} is not a sha256. Write the "
                    f"full 64 lowercase hex characters of the document's "
                    f"UTF-8 bytes with line feeds — a placeholder here reads "
                    f"as a real digest to every later gate."
                )
            if path in found:
                raise DocsConceptsError(
                    f"{where}/path: {path} is listed twice. One document, one "
                    f"pin — two pins on one file can disagree."
                )
            found[path] = (self._source(path, where), pinned)
        return found

    # -- the section anchors -----------------------------------------------

    def _read_authorities(
        self,
        raw: Any,
        sources: Mapping[str, tuple[_Source, str]],
        own: _Source,
        findings: list[Finding],
    ) -> dict[str, AuthorityRef]:
        """One record per cited section, each anchor checked against the file."""
        entries = _array(raw, f"{own.path}#/authorities")
        found: dict[str, AuthorityRef] = {}
        stale: dict[str, list[str]] = {}
        for index, entry in enumerate(entries):
            where = f"{own.path}#/authorities/{index}"
            item = _object(entry, where)
            _exactly(item, ("heading", "id", "section", "source"), where)
            identifier = _text(item["id"], f"{where}/id")
            if id_form(identifier) != "authority":
                raise DocsConceptsError(
                    f"{where}/id: {identifier!r} is not an authority id. A "
                    f"cited section is addressed as "
                    f"authority:<class>/<stable-name>, and the class segment "
                    f"is the one a gate compares against the record's own "
                    f"class field."
                )
            validate_id(identifier)
            if identifier in found:
                raise DocsConceptsError(
                    f"{where}/id: {identifier} is declared twice. One section, "
                    f"one record — two records under one id would reach the "
                    f"merge rule as a disagreement with itself."
                )
            path = _text(item["source"], f"{where}/source")
            if path not in sources:
                raise DocsConceptsError(
                    f"{where}/source: {path} is not one of the documents this "
                    f"file pins. Add it to sources with its digest, so the "
                    f"citation can be re-verified rather than trusted."
                )
            source, pinned = sources[path]
            section = _text(item["section"], f"{where}/section")
            heading = self._resolve_heading(source, section, f"{where}/section")
            recorded = _text(item["heading"], f"{where}/heading")
            if source.digest != pinned:
                stale.setdefault(path, []).append(f"{section} ({identifier})")
            elif recorded != heading:
                findings.append(
                    _heading_moved(own.path, where, identifier, section, recorded, heading)
                )
            found[identifier] = AuthorityRef(
                id=identifier,
                authority_class=identifier.partition(":")[2].partition("/")[0],
                source=source.path,
                section=section,
                content_sha256=source.digest,
                status="Current",
                delegates=(),
            )
        if not found:
            raise DocsConceptsError(
                f"{own.path}#/authorities: is empty. Every concept in this "
                f"file cites at least one section, and a section nobody "
                f"declared cannot be cited."
            )
        for path, cited in sorted(stale.items()):
            findings.append(_stale_finding(own.path, path, sources[path], sorted(cited)))
        return found

    def _resolve_heading(self, source: _Source, section: str, where: str) -> str:
        """The one heading ``section`` opens, refusing none and refusing two."""
        headings = headings_by_number(source.text).get(section, ())
        if len(headings) == 1:
            return headings[0]
        if not headings:
            raise DocsConceptsError(
                f"{where}: {source.path} has no heading numbered {section!r}. "
                f"A citation is anchored on the heading's own number, which "
                f"is what other documents cite and what moves only on a "
                f"restructure; check whether the section was renumbered."
            )
        raise DocsConceptsError(
            f"{where}: {source.path} has {len(headings)} headings numbered "
            f"{section!r} ({', '.join(repr(item) for item in headings)}). An "
            f"ambiguous citation fails here rather than picking a winner."
        )

    # -- what lives elsewhere ----------------------------------------------

    def _read_external_ids(self, raw: Any, own: _Source) -> tuple[str, ...]:
        """The ids this file cites and another provider emits."""
        entries = _array(raw, f"{own.path}#/external_ids")
        found: list[str] = []
        for index, entry in enumerate(entries):
            where = f"{own.path}#/external_ids/{index}"
            identifier = _text(entry, where)
            validate_id(identifier)
            if identifier in found:
                raise DocsConceptsError(f"{where}: {identifier} is listed twice")
            found.append(identifier)
        if found != sorted(found):
            raise DocsConceptsError(
                f"{own.path}#/external_ids: is not sorted. Sorted lists are "
                f"what make two readings of this file byte-identical."
            )
        return tuple(found)

    # -- the concepts themselves -------------------------------------------

    def _read_concepts(
        self,
        raw: Any,
        own: _Source,
        authorities: frozenset[str],
        external_ids: tuple[str, ...],
    ) -> dict[str, ConceptRecord]:
        """One record per authored concept, every reference checked."""
        entries = _array(raw, f"{own.path}#/records")
        known_authorities = authorities | set(external_ids)
        found: dict[str, ConceptRecord] = {}
        order: list[str] = []
        for index, entry in enumerate(entries):
            where = f"{own.path}#/records/{index}"
            record = _read_concept(entry, where, known_authorities)
            if record.id in found:
                raise DocsConceptsError(
                    f"{where}/id: {record.id} is declared twice in one file"
                )
            found[record.id] = record
            order.append(record.id)
        if not found:
            raise DocsConceptsError(
                f"{own.path}#/records: is empty. A concepts file that teaches "
                f"nothing passes every check it is subject to."
            )
        if order != sorted(order):
            raise DocsConceptsError(
                f"{own.path}#/records: is not sorted by id. The provider "
                f"contract says sorted, and the sorted file is what a "
                f"reviewer reads."
            )
        _check_relation_targets(found, own.path, external_ids)
        return found

    # -- alternate terms ---------------------------------------------------

    def _read_aliases(
        self,
        raw: Any,
        own: _Source,
        concepts: frozenset[str],
        external_ids: tuple[str, ...],
    ) -> AliasIndex:
        """Old or alternate ids mapped forward to the concept that answers."""
        entries = _object(raw, f"{own.path}#/aliases")
        known = concepts | set(external_ids)
        pairs: list[tuple[str, str]] = []
        for alias in sorted(entries):
            where = f"{own.path}#/aliases/{alias}"
            if id_form(alias) != "concept":
                raise DocsConceptsError(
                    f"{where}: {alias!r} is not a concept id. An alternate "
                    f"term is addressed the same way the term it replaces is."
                )
            if alias in concepts:
                raise DocsConceptsError(
                    f"{where}: {alias} is a concept this file declares, so it "
                    f"cannot also be another concept's alternate name. One id "
                    f"answers to one thing."
                )
            target = _text(entries[alias], where)
            if target not in known:
                raise DocsConceptsError(
                    f"{where}: {target} is not a concept this file declares "
                    f"and is not listed in external_ids, so the alternate "
                    f"term leads nowhere."
                )
            pairs.append((alias, target))
        return AliasIndex.of(pairs)


# ---------------------------------------------------------------------------
# One concept, read
# ---------------------------------------------------------------------------

_CONCEPT_KEYS = (
    "do_not_use_when",
    "examples",
    "governed_by",
    "id",
    "plain_definition",
    "purpose",
    "related_concepts",
    "summary",
    "syntax",
    "term",
    "use_when",
)


def _read_concept(entry: Any, where: str, known_authorities: frozenset[str]) -> ConceptRecord:
    """One authored concept as a record, refusing every shape it is not."""
    item = _object(entry, where)
    _exactly(item, _CONCEPT_KEYS, where)

    identifier = _text(item["id"], f"{where}/id")
    if id_form(identifier) != "concept":
        raise DocsConceptsError(
            f"{where}/id: {identifier!r} is not a concept id. A taught idea "
            f"is addressed by its term as a lowercase hyphenated slug — "
            f"concept:self-knowledge."
        )
    validate_id(identifier)

    term = _text(item["term"], f"{where}/term")
    if identifier != f"concept:{_slug(term)}":
        raise DocsConceptsError(
            f"{where}/term: the id is {identifier!r} and the term is "
            f"{term!r}, which slugs to {_slug(term)!r}. The id is the term "
            f"written as a slug, so a reader who searches for the word "
            f"reaches the record; make them agree."
        )

    governed_by = _id_list(item["governed_by"], f"{where}/governed_by")
    if not governed_by:
        raise DocsConceptsError(
            f"{where}/governed_by: {identifier} cites nothing. A taught "
            f"meaning that answers to no written authority is an opinion, and "
            f"this model does not carry opinions."
        )
    for index, cited in enumerate(governed_by):
        if cited not in known_authorities:
            raise DocsConceptsError(
                f"{where}/governed_by/{index}: {identifier} cites {cited}, "
                f"which this file neither declares in authorities nor lists "
                f"in external_ids. Declare the section it points at, or name "
                f"the provider's id in external_ids — a citation nothing "
                f"answers to is worse than none."
            )

    return ConceptRecord(
        id=identifier,
        term=term,
        summary=_text(item["summary"], f"{where}/summary"),
        plain_definition=_text(item["plain_definition"], f"{where}/plain_definition"),
        purpose=_text(item["purpose"], f"{where}/purpose"),
        use_when=_text(item["use_when"], f"{where}/use_when"),
        do_not_use_when=_text(item["do_not_use_when"], f"{where}/do_not_use_when"),
        governed_by=governed_by,
        examples=_read_examples(item["examples"], f"{where}/examples"),
        syntax=_read_syntax(item["syntax"], f"{where}/syntax"),
        related_concepts=_read_relations(item["related_concepts"], f"{where}/related_concepts"),
    )


def _id_list(raw: Any, where: str) -> tuple[str, ...]:
    """A sorted list of well-formed, distinct ids."""
    entries = _array(raw, where)
    found: list[str] = []
    for index, entry in enumerate(entries):
        identifier = _text(entry, f"{where}/{index}")
        validate_id(identifier)
        if identifier in found:
            raise DocsConceptsError(f"{where}/{index}: {identifier} is listed twice")
        found.append(identifier)
    if found != sorted(found):
        raise DocsConceptsError(f"{where}: is not sorted")
    return tuple(found)


def _read_examples(raw: Any, where: str) -> tuple[ExampleRef, ...]:
    """The registered runnable examples a concept points at."""
    entries = _array(raw, where)
    found: list[ExampleRef] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        item = _object(entry, at)
        _exactly(item, ("id", "source"), at)
        identifier = _text(item["id"], f"{at}/id")
        if id_form(identifier) != "example":
            raise DocsConceptsError(
                f"{at}/id: {identifier!r} is not an example id. One colon, "
                f"always — the doubled form is the authoring syntax for an "
                f"entity reference inside prose, which is a different thing."
            )
        found.append(ExampleRef(id=identifier, source=_text(item["source"], f"{at}/source")))
    ids = [item.id for item in found]
    if ids != sorted(ids):
        raise DocsConceptsError(f"{where}: is not sorted by id")
    return tuple(found)


def _read_syntax(raw: Any, where: str) -> tuple[str, ...]:
    """The smallest valid written form, one line per line.

    Order is the author's, not sorted: a declaration skeleton read out of
    order is not a skeleton. Blank and trailing-space lines are refused
    because a written form is quoted verbatim into several channels, and a
    trailing space is invisible in exactly the place it would diverge.
    """
    entries = _array(raw, where)
    found: list[str] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        if not isinstance(entry, str):
            raise DocsConceptsError(f"{at}: expected text, got {_named(entry)}")
        if not entry.strip():
            raise DocsConceptsError(
                f"{at}: is blank. A syntax form is quoted verbatim into every "
                f"channel that shows it; a blank line inside one is a "
                f"whitespace difference nothing downstream can see."
            )
        if entry != entry.rstrip():
            raise DocsConceptsError(f"{at}: ends in whitespace")
        found.append(entry)
    return tuple(found)


def _read_relations(raw: Any, where: str) -> tuple[tuple[str, ...], ...]:
    """The typed edges to other concepts: relation first, then the target."""
    entries = _array(raw, where)
    found: list[tuple[str, ...]] = []
    for index, entry in enumerate(entries):
        at = f"{where}/{index}"
        pair = _array(entry, at)
        if len(pair) != 2:
            raise DocsConceptsError(
                f"{at}: a relationship is a relation and the concept it points "
                f"at, in that order — two values, and this one has {len(pair)}."
            )
        relation = _text(pair[0], f"{at}/0")
        relation_of(relation)
        target = _text(pair[1], f"{at}/1")
        if id_form(target) != "concept":
            raise DocsConceptsError(
                f"{at}/1: {target!r} is not a concept id. A concept relates to "
                f"another concept; a citation of a document is governed_by and "
                f"a demonstration is an example."
            )
        validate_id(target)
        found.append((relation, target))
    if found != sorted(found):
        raise DocsConceptsError(f"{where}: is not sorted")
    if len(set(found)) != len(found):
        raise DocsConceptsError(f"{where}: declares the same relationship twice")
    return tuple(found)


def _check_relation_targets(
    concepts: Mapping[str, ConceptRecord], path: str, external_ids: tuple[str, ...]
) -> None:
    """Every declared edge points at something, and nothing points at itself."""
    known = set(concepts) | set(external_ids)
    for index, concept_id in enumerate(sorted(concepts)):
        record = concepts[concept_id]
        for position, (relation, target) in enumerate(record.related_concepts):
            at = f"{path}#/records/{index}/related_concepts/{position}"
            if target == record.id:
                raise DocsConceptsError(
                    f"{at}: {record.id} declares itself {relation} itself. A "
                    f"concept is not related to itself; every relation here "
                    f"says something about a *pair*."
                )
            if target not in known:
                raise DocsConceptsError(
                    f"{at}: {record.id} is {relation} {target}, which this "
                    f"file neither declares nor lists in external_ids. Write "
                    f"the concept, correct the id, or name it in external_ids "
                    f"so the composition can resolve it."
                )


def _stamp(provider_id: str, source: _Source) -> Provenance:
    """This provider's account of having read the authored file."""
    return Provenance(
        adapter_id=provider_id,
        schema_version=SCHEMA,
        source=source.path,
        source_sha256=source.digest,
    )


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _stale_finding(
    concepts_path: str, cited_path: str, source: tuple[_Source, str], sections: Sequence[str]
) -> Finding:
    """One ``DOC_AUTHORITY_STALE``, naming every section that has to be re-read."""
    live, pinned = source[0].digest, source[1]
    return Finding(
        code=DOC_AUTHORITY_STALE,
        location=cited_path,
        message=(
            f"{concepts_path} pins {cited_path} at {pinned} and the file now "
            f"hashes to {live}, so these citations have not been re-read since "
            f"it changed: {', '.join(sections)}"
        ),
        remediation=(
            f"open each section listed above, check the concept still says "
            f"what the section says, then write {live} into the sources entry "
            f"for {cited_path}. Confirm it independently with "
            f"`shasum -a 256 {cited_path}` (or `sha256sum`) — the digest is "
            f"over the file's UTF-8 bytes with line feeds. Re-pinning without "
            f"re-reading is the one thing this check exists to prevent."
        ),
    )


def _heading_moved(
    concepts_path: str,
    where: str,
    identifier: str,
    section: str,
    recorded: str,
    live: str,
) -> Finding:
    """The section number still resolves, and to a differently worded heading."""
    return Finding(
        code=DOC_AUTHORITY_STALE,
        location=where,
        message=(
            f"{identifier} records section {section} as {recorded!r} and the "
            f"heading now reads {live!r}"
        ),
        remediation=(
            f"the number still resolves, so the anchor is intact; read the "
            f"section to see whether the rewording changed what it says, then "
            f"write the new heading into {concepts_path}. The number is the "
            f"anchor and the heading is the check — they are not the same job."
        ),
    )


def check_voice(record: ConceptRecord, location: str) -> list[Finding]:
    """Every authored prose field is written in the product's own voice.

    ``DOC_VOICE_VIOLATION``.
    The fields are the ones C1 classifies ``AUTHORED_PROSE``, read from
    :data:`~s0ma_dsl.docs_model.records.FIELD_CLASS` rather than listed
    here, so a field added to the record is governed the moment it is
    classified. This is the boundary B4 found the hard way: a quotation of
    a component's real intent may contain a word the voice forbids, and a
    voice rule applied to a quotation makes either a false quotation or a
    permanently failing gate.
    """
    findings: list[Finding] = []
    for name in authored_prose_fields(ConceptRecord):
        written = getattr(record, name)
        if not isinstance(written, str):
            continue
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(written)
            if found is None:
                continue
            findings.append(
                Finding(
                    code=DOC_VOICE_VIOLATION,
                    location=location,
                    message=(
                        f"{record.id}.{name} uses {found.group(0)!r}, which is "
                        f"{label} and not a word this product uses in text a "
                        f"reader sees"
                    ),
                    remediation=(
                        "write the plain-language term instead. The product "
                        "says feedback data, and it spells its own names with "
                        "a digit zero. This field is authored prose, so the "
                        "rule reaches it; a quoted intent is sourced, and the "
                        "rule deliberately does not."
                    ),
                )
            )
    return findings


def _one_sided_findings(
    concepts: Sequence[ConceptRecord], path: str, external_ids: tuple[str, ...]
) -> list[Finding]:
    """Symmetric relations declared from one end only, within one file."""
    declared = {record.id: record for record in concepts}
    external = set(external_ids)
    findings: list[Finding] = []
    for record in sorted(concepts, key=lambda item: item.id):
        for relation, target in record.related_concepts:
            if relation not in SYMMETRIC_RELATIONS or target in external:
                continue
            other = declared.get(target)
            if other is None or (relation, record.id) in other.related_concepts:
                continue
            findings.append(_one_sided(record.id, other.id, relation, path))
    return findings


def _one_sided(source_id: str, target_id: str, relation: str, location: str) -> Finding:
    """One ``DOC_RELATION_ONE_SIDED``, naming both ends and the missing edge."""
    return Finding(
        code=DOC_RELATION_ONE_SIDED,
        location=location,
        message=(
            f"{source_id} is {relation} {target_id} and {target_id} does not "
            f"say so back, though {relation} is symmetric"
        ),
        remediation=(
            f'add ["{relation}", "{source_id}"] to {target_id}, or use a '
            f"relation that runs one way. A reader arriving at either concept "
            f"has to be told about the other; an edge visible from one end "
            f"only answers the reverse query differently depending on where "
            f"you start."
        ),
    )


# ---------------------------------------------------------------------------
# The validate-time gate
# ---------------------------------------------------------------------------


def check_concept_relations(bundle: DocsBundle) -> list[Finding]:
    """Every concept-to-concept edge in a composed bundle holds.

    Run after composition rather than inside a provider, because the two
    concept files cite each other: a language concept and a product concept
    are one graph, and neither reading can see the whole of it on its own.
    Within one file the loader has already refused an unresolvable target;
    this is where a target that was promised to another provider is held to
    that promise.

    ``DOC_CONCEPT_UNRESOLVED`` is §11's own name for "a relationship names
    a concept absent from the catalog", so nothing is minted for it here.
    """
    from s0ma_dsl.docs_model.validate import DOC_CONCEPT_UNRESOLVED

    known = {normalize_id(record.id): record for record in bundle.concepts}
    findings: list[Finding] = []
    for record in sorted(bundle.concepts, key=lambda item: item.id):
        for relation, target in record.related_concepts:
            resolved = known.get(normalize_id(target))
            if resolved is None:
                findings.append(
                    Finding(
                        code=DOC_CONCEPT_UNRESOLVED,
                        location="",
                        message=(
                            f"{record.id} is {relation} {target}, which this "
                            f"build does not address"
                        ),
                        remediation=(
                            f"either {record.id} names the wrong id, or "
                            f"{target} is a concept nobody has written yet. "
                            f"The concept files are the authored source; add "
                            f"the record there or correct the citation."
                        ),
                    )
                )
                continue
            if relation in SYMMETRIC_RELATIONS and (
                relation,
                record.id,
            ) not in resolved.related_concepts:
                findings.append(_one_sided(record.id, resolved.id, relation, ""))
    return findings
