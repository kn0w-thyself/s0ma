"""The repository's own written authority, read as an index.

Milestone C4 of the docs-function plan (internal) §8, implementing the
architecture plan's §7.6. Everything else in the documentation application
cites an authority for what it says; this provider is what those citations
resolve against. It reads the files a decision was actually written down in
— the PRD, all three ADR trees, the frozen contracts, the current language
specification, the changelog's release identity and the four distributions'
package metadata — and emits one
:class:`~s0ma_dsl.docs_model.records.AuthorityRef` per addressable thing.

**What this module reads, and what it refuses to read.** Architecture §7.6
is explicit: "normative prose is not parsed for arbitrary semantic
inference. The provider registers explicit requirement ids, versions,
status, content hashes, and relationships authored in the catalog." So the
whole of what is extracted from any file here is:

* an id at the start of a line (``- **FR-DSL-1**``, ``ADR-004`` from a
  filename);
* a heading, verbatim, as the section a record sits in;
* a ``**Status:**`` line's first word, matched against a closed vocabulary;
* the ``Term`` column of one table — the glossary's — which holds names,
  not prose;
* TOML keys from ``pyproject.toml``;
* the sha256 of the file.

No requirement's body is read. No sentence is interpreted. The one
*relationship* in the output that a sentence justifies — FR-DSL-1 handing
language authority to the versioned specification — is written down here by
hand, in :data:`PRD_DELEGATIONS`, with the section that says so; it is not
inferred from the prose, and :func:`RepoProvider.provide` refuses to run if
the id it cites has left the PRD.

**One file hash per file.** Every record derived from the PRD carries the
PRD's digest, not a digest of its own section. Markdown sections are not
separable byte ranges — a heading level changes, a table gains a row, and a
"section hash" silently means something else — so the honest unit is the
file. The cost is that an unrelated PRD edit re-stamps every PRD record;
that is the intended behavior (plan §8 C4: "PRD hash changes flip the
affected authority records"), because a citation into a document that moved
is a citation that has to be re-read.

**Absence is empty, never an error.** A tree without a ``docs/contracts``
directory produces no contract records rather than an exception: this
provider cannot know which of its sources a given repository is supposed to
have, and the gate that does know is
:func:`~s0ma_dsl.docs_model.validate.check_floors`. What *is* an error is a
file this module can see and cannot address — a contract whose filename
makes no valid id, an ADR without a number — because silently skipping one
would drop a written authority out of the index without saying so.

**Field classification.** C1 classifies most of ``AuthorityRef`` as
``AUTHORED_DATA``, which is the model's statement that no voice rule
applies to those fields — not a statement that no provider may derive them.
Every field this module emits is derived, and every one of them is an
identifier, a path, a heading or a status word.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.docs_model.ids import validate_id
from s0ma_dsl.docs_model.providers import (
    DocsProviderError,
    ProviderResult,
    SourcedRecord,
    sort_records,
)
from s0ma_dsl.docs_model.records import (
    SCHEMA,
    AuthorityDelegation,
    AuthorityRef,
    Provenance,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "CHANGELOG",
    "CONTRACTS_DIR",
    "DECISION_WORDS",
    "LANGUAGE_DOMAIN",
    "PRD",
    "PRD_DELEGATIONS",
    "PROVIDER_ID",
    "REPOSITORY_FLOORS",
    "REQUIREMENT_FAMILIES",
    "SPEC_DIR",
    "UNKNOWN_DECISION",
    "PackageFacts",
    "RepoProvider",
    "decision_of",
    "facts_of",
    "package_facts",
    "status_line",
]

#: This adapter's id, and the ``adapter_id`` it stamps on every record.
PROVIDER_ID = "repo"

# ---------------------------------------------------------------------------
# Where the written authority lives, repository-relative
# ---------------------------------------------------------------------------

#: The product requirements. Canonical for purpose and requirements; the
#: language specification is canonical for what the language means, and
#: :data:`PRD_DELEGATIONS` is where the PRD says so.
PRD = "references/s0ma-prd.md"

#: The frozen wire and budget contracts.
CONTRACTS_DIR = "docs/contracts"

#: Where the versioned language specifications live. The current one is the
#: highest version present — derived here rather than read from
#: ``tests/test_doc_consistency.py``'s ``CURRENT_SPEC_VERSION`` pin, which
#: is a test and not importable from shipped code. The two agreeing is what
#: makes the pin worth having; a provider that read the pin could not
#: disagree with it.
SPEC_DIR = "packages/s0ma-dsl/docs"

#: The one changelog (INV-4), which carries the release identity.
CHANGELOG = "CHANGELOG.md"

#: The requirement families the PRD numbers. Every alternative is tried at
#: the same anchored position — right after the ``- **`` a declaration
#: opens with — so their order does not decide between them and an id
#: mentioned mid-sentence matches none of them.
#:
#: ``P`` — the principles — is here alongside the three the milestone names
#: because the PRD's own §12 governs "Principles or Invariants" as one
#: class, and the glossary cites ``P-1`` and ``P-2`` as governing entries.
#: An index that could not resolve those citations would be incomplete for
#: exactly the records that need it. Removing the family is a one-line
#: change here.
REQUIREMENT_FAMILIES: tuple[str, ...] = ("FR", "NFR", "INV", "P")

#: The domain FR-DSL-1 hands to the specification. Callers asking the
#: authority comparison a language question pass this exact string —
#: :func:`~s0ma_dsl.docs_model.validate.governing_authority` matches a
#: delegation's domain by equality, so the constant is shared rather than
#: spelled twice.
LANGUAGE_DOMAIN = "language"

#: Delegations this repository's authorities have written down, keyed by
#: the requirement id that states one.
#:
#: Hand-authored on purpose, and the only hand-authored thing in this
#: module. FR-DSL-1 says, in the PRD's own words, that the versioned spec
#: is the normative language authority and that the PRD does not duplicate
#: it. Deriving that from the sentence would be the semantic inference §7.6
#: forbids; asserting it without a citation would be the assumption C1's
#: :class:`~s0ma_dsl.docs_model.records.AuthorityDelegation` exists to
#: refuse. So it is written here with the section that states it, and
#: :meth:`RepoProvider.provide` refuses to run if the PRD stops carrying
#: the id — a delegation whose citation has gone is worse than none.
PRD_DELEGATIONS: Mapping[str, tuple[AuthorityDelegation, ...]] = {
    "FR-DSL-1": (
        AuthorityDelegation(
            domain=LANGUAGE_DOMAIN,
            to_class="spec",
            stated_in="§7.2 FR-DSL-1",
        ),
    ),
}

#: The words a governance document's ``**Status:**`` line may open with,
#: and the form each is recorded as. Closed on purpose: a status this
#: module has never seen becomes :data:`UNKNOWN_DECISION` rather than a new
#: word entering the vocabulary through a typo. Only the first word is
#: read — "Accepted — owner-ratified 2026-08-27 (FD-1..FD-13)" is
#: ``Accepted``, and the rest of that line stays where it was written.
DECISION_WORDS: Mapping[str, str] = {
    "accepted": "Accepted",
    "deprecated": "Deprecated",
    "draft": "Draft",
    "frozen": "Frozen",
    "living": "Living",
    "proposed": "Proposed",
    "rejected": "Rejected",
    "superseded": "Superseded",
}

#: What an unrecognized status becomes. Visible, and never silently
#: "Accepted".
UNKNOWN_DECISION = "Unknown"

#: An anti-vacuity floor for this repository, for the build to hand
#: :func:`~s0ma_dsl.docs_model.validate.check_floors`.
#:
#: Floors are the caller's, never the model's — but this provider reads
#: *this* repository, so the claim belongs with it. The number is well
#: below the live count, so ordinary authoring never trips it, and far
#: above anything a partial read produces: the failure it exists to catch
#: is a source that moved and a provider that consequently sees nothing.
REPOSITORY_FLOORS: Mapping[tuple[str, str], int] = {(PROVIDER_ID, "authorities"): 100}


# ---------------------------------------------------------------------------
# Patterns
#
# Every one is anchored at the start of a line. A requirement id mentioned
# inside a sentence, a changelog row or a cross-reference is not a
# declaration of that requirement, and matching one would put the same id
# in the index twice with two different sections.
# ---------------------------------------------------------------------------

_FAMILY = "|".join(f"{name}-[A-Z0-9]+" if name == "FR" else name for name in REQUIREMENT_FAMILIES)

#: ``- **FR-CORE-1** MUST ...`` / ``- **INV-1 — Spelling.** ...``. The
#: trailing guard stops ``INV-1`` matching the first half of ``INV-12``.
_REQUIREMENT = re.compile(rf"^-\s+\*\*(?P<id>(?:{_FAMILY})-\d+)(?![A-Za-z0-9-])")

#: Any markdown heading, with its level, so the section a record sits in is
#: the nearest heading above it.
_HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")

#: The bolded first cell of a table row: the glossary's ``Term`` column.
_TERM = re.compile(r"^\|\s*\*\*(?P<term>.+?)\*\*\s*\|")

#: ``**Status:** Accepted — owner-ratified ...``
_STATUS = re.compile(r"^\*\*Status:\*\*\s*(?P<rest>.*)$")

#: The first word of a status line, once its bold markers are stripped.
_WORD = re.compile(r"[A-Za-z]+")

#: A labelled row of a document's header table:
#: ``| **Version** | 1.9 (2026-08-27) |``. The label goes in by name.
_HEADER_ROW = r"^\|\s*\*\*{label}\*\*\s*\|\s*(?P<value>[^|]*?)\s*\|"

#: ``## [0.18.1] — 2026-08-28`` and ``## [Unreleased]``.
_RELEASE = re.compile(r"^##\s+\[(?P<name>[^\]]+)\]\s*(?:[—-]\s*(?P<date>\S+))?")

#: ``ADR-012-docs-application.md`` → ``012``.
_ADR_FILE = re.compile(r"^ADR-(?P<number>\d+)-")

#: ``s0ma-dsl-spec-v0.17.0.md`` → ``0.17.0``.
_SPEC_FILE = re.compile(r"^s0ma-dsl-spec-v(?P<version>\d+(?:\.\d+)*)$")

#: The distribution name at the front of a dependency specifier:
#: ``s0ma-core[mcp] >= 0.16.2`` → ``s0ma-core``.
_DIST = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")

#: Everything that is not a lowercase letter or digit, for slugs.
_NOT_SLUG = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# The status field's grammar
#
# ``AuthorityRef`` carries one free-text field, ``status``, and this
# provider has facts that belong on a record and nowhere to put them: a
# package's version and dependency direction, which ADR tree a decision
# lives in, whether an index lists it. Rather than invent a field inside
# ``@1``, they ride in ``status`` under one documented grammar:
#
#     <word>[; <key>=<value>]*
#
# The two functions below are the only supported way to read it back, so a
# consumer never string-splits by hand and the grammar has one definition.
# This is a stopgap and it is worth saying so: the model has no record type
# for a distribution, and the package-inventory source the architecture
# plan's §7.7 names is where these facts eventually belong.
# ---------------------------------------------------------------------------


def status_line(word: str, facts: Mapping[str, str] | None = None) -> str:
    """One status string: a decision word, then sorted ``key=value`` facts."""
    if not word or ";" in word or "=" in word:
        raise DocsProviderError(
            f"{word!r} is not a status word; a status opens with one word and "
            f"its facts follow after a semicolon"
        )
    if not facts:
        return word
    written = "; ".join(f"{key}={facts[key]}" for key in sorted(facts))
    return f"{word}; {written}"


def decision_of(status: str) -> str:
    """The decision word of a status string, without its facts."""
    return status.partition(";")[0].strip()


def facts_of(status: str) -> Mapping[str, str]:
    """The ``key=value`` facts of a status string, keyed by name."""
    found: dict[str, str] = {}
    for part in status.split(";")[1:]:
        key, separator, value = part.partition("=")
        if separator:
            found[key.strip()] = value.strip()
    return found


# ---------------------------------------------------------------------------
# Reading files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Source:
    """One file, read once: where it is, what it says, what it hashes to."""

    path: str
    text: str
    digest: str

    @property
    def lines(self) -> list[str]:
        return self.text.split("\n")


def _digest_of(text: str) -> str:
    """The sha256 of ``text`` as LF-normalized UTF-8 bytes.

    Equal to what ``sha256sum`` reports for the tracked file, and equal in
    a checkout that lost the line-feed attribute — the normalization is
    what makes the second half true. Full 64 hex characters, the form
    :func:`~s0ma_dsl.docs_model.validate.check_provenance` requires and the
    form ``AuthorityRef.content_sha256`` therefore also uses: two digests
    of one file that differ in shape invite a false mismatch.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    """A lowercase hyphenated slug of ``text``, with markup dropped."""
    return _NOT_SLUG.sub("-", text.replace("`", "").strip().lower()).strip("-")


def _heading_above(lines: Sequence[str], index: int) -> str:
    """The nearest heading at or above ``index``, verbatim, or ``""``."""
    for line in reversed(lines[: index + 1]):
        found = _HEADING.match(line)
        if found:
            return found.group("title")
    return ""


def _first_heading(source: _Source) -> str:
    """The document's own title, verbatim, or ``""`` where it has none."""
    for line in source.lines:
        found = _HEADING.match(line)
        if found:
            return found.group("title")
    return ""


def _declared_status(source: _Source) -> str:
    """The decision word of a ``**Status:**`` line, or the unknown one.

    The line is found structurally and only its first word is classified.
    Everything after that word — the ratification date, the milestone, the
    owner-decision list — is prose, and this module does not read prose.
    """
    for line in source.lines:
        found = _STATUS.match(line)
        if not found:
            continue
        word = _WORD.search(found.group("rest").replace("*", ""))
        if word is None:
            break
        return DECISION_WORDS.get(word.group(0).lower(), UNKNOWN_DECISION)
    return UNKNOWN_DECISION


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoProvider:
    """The written authority of one checkout, indexed.

    ``root`` is the immutable input the provider contract asks for: the
    repository the records describe, fixed when the provider is built and
    never re-resolved at call time. Point it at a copy and the records
    describe the copy — which is how the hash-flip behavior is proved.

    Nothing here writes, and nothing here opens a socket. Every path is
    recorded repository-relative in POSIX form, so a record carries no
    trace of the machine that built it (INV-5).
    """

    root: Path
    _cache: dict[str, _Source | None] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def provider_id(self) -> str:
        """This adapter's stable id."""
        return PROVIDER_ID

    # -- reading -----------------------------------------------------------

    def _source(self, relative: str) -> _Source | None:
        """One file of the checkout, or ``None`` where it is absent.

        Read once per ``provide()`` and remembered, so a file every record
        of a group shares — the PRD, an ADR index — is hashed once and
        every record derived from it carries the same digest by
        construction rather than by two readings agreeing.
        """
        if relative in self._cache:
            return self._cache[relative]
        path = self.root / relative
        source: _Source | None = None
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            source = _Source(path=relative, text=text, digest=_digest_of(text))
        self._cache[relative] = source
        return source

    def _relative(self, path: Path) -> str:
        """``path`` as a repository-relative POSIX string."""
        return path.relative_to(self.root).as_posix()

    def _markdown_in(self, relative: str, pattern: str) -> list[_Source]:
        """Every file of ``relative`` matching ``pattern``, sorted by name."""
        directory = self.root / relative
        if not directory.is_dir():
            return []
        found: list[_Source] = []
        for path in sorted(directory.glob(pattern)):
            source = self._source(self._relative(path))
            if source is not None:
                found.append(source)
        return found

    # -- emitting ----------------------------------------------------------

    def _stamp(self, source: _Source) -> Provenance:
        """This provider's account of having read ``source``."""
        return Provenance(
            adapter_id=PROVIDER_ID,
            schema_version=SCHEMA,
            source=source.path,
            source_sha256=source.digest,
        )

    def _authority(
        self,
        *,
        identifier: str,
        authority_class: str,
        source: _Source,
        section: str,
        status: str,
        delegates: tuple[AuthorityDelegation, ...] = (),
    ) -> SourcedRecord:
        """One authority record, its id checked before it is minted."""
        validate_id(identifier)
        return SourcedRecord(
            record=AuthorityRef(
                id=identifier,
                authority_class=authority_class,
                source=source.path,
                section=section,
                content_sha256=source.digest,
                status=status,
                delegates=delegates,
            ),
            provenance=self._stamp(source),
        )

    def provide(self) -> ProviderResult:
        """Read the checkout and return its authority index, sorted.

        One id twice is refused here rather than left to the composition.
        Two providers claiming an id is the merge rule's business; *one*
        provider claiming an id twice is a bug in this module, and the
        composition would report it as though two sources disagreed.
        """
        records = [
            *self._prd_records(),
            *self._adr_records(),
            *self._contract_records(),
            *self._spec_records(),
            *self._release_records(),
            *self._package_records(),
        ]
        seen: dict[str, str] = {}
        repeated: list[str] = []
        for item in records:
            held = seen.get(item.record.id)
            if held is not None:
                repeated.append(f"{item.record.id} (from {held} and {item.provenance.source})")
            seen[item.record.id] = item.provenance.source
        if repeated:
            raise DocsProviderError(
                f"provider {PROVIDER_ID!r} emitted the same id more than once: "
                f"{'; '.join(sorted(repeated))}. One authority has one record; "
                f"qualify the id with what distinguishes the two sources."
            )
        return ProviderResult(provider_id=PROVIDER_ID, records=sort_records(records))

    # -- the product requirements -----------------------------------------

    def _prd_records(self) -> list[SourcedRecord]:
        """The PRD's document identity, its requirement ids, its glossary.

        Every record shares the PRD's digest. The delegation table is
        applied here and checked here: a delegation citing a requirement
        the PRD no longer carries stops the build, because the alternative
        is an index that quietly stops honoring a handover the language
        depends on.
        """
        source = self._source(PRD)
        if source is None:
            return []
        lines = source.lines
        declared, version = _prd_identity(source)
        records = [
            self._authority(
                identifier="authority:prd/document",
                authority_class="prd",
                source=source,
                section="",
                status=status_line(declared, {"version": version}),
            )
        ]

        seen: set[str] = set()
        for index, line in enumerate(lines):
            found = _REQUIREMENT.match(line)
            if found is None:
                continue
            identifier = found.group("id")
            if identifier in seen:
                # The PRD numbering one id twice is a PRD problem, not an
                # index problem. The first declaration wins so the record
                # set stays a function of the file rather than of which
                # copy was read last.
                continue
            seen.add(identifier)
            records.append(
                self._authority(
                    identifier=f"authority:prd/{identifier}",
                    authority_class="prd",
                    source=source,
                    section=_heading_above(lines, index),
                    status="Current",
                    delegates=PRD_DELEGATIONS.get(identifier, ()),
                )
            )

        uncited = sorted(set(PRD_DELEGATIONS) - seen)
        if uncited:
            raise DocsProviderError(
                f"{PRD} no longer declares {', '.join(uncited)}, and this "
                f"provider records a delegation stated there. A delegation "
                f"whose citation has gone is an assumption — re-point it at "
                f"the requirement that carries the handover now, or drop it "
                f"from PRD_DELEGATIONS if the handover itself has gone."
            )

        records.extend(self._glossary_records(source))
        return records

    def _glossary_records(self, source: _Source) -> list[SourcedRecord]:
        """One record per glossary term, expanding the shared rows.

        Four of the glossary's rows define several terms at once — the
        declaration kinds share one row, the documentation declarations
        share another — and each of those terms is separately citable, so
        each gets a record. Splitting the ``Term`` column on its slashes is
        reading a list of names, not interpreting prose: the ``Meaning``
        column is never touched.
        """
        lines = source.lines
        records: list[SourcedRecord] = []
        seen: set[str] = set()
        inside = False
        section = ""
        for line in lines:
            heading = _HEADING.match(line)
            if heading is not None:
                section = heading.group("title")
                inside = "glossary" in _slug(section).split("-")
                continue
            if not inside:
                continue
            term = _TERM.match(line)
            if term is None:
                continue
            for part in term.group("term").split("/"):
                slug = _slug(part)
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                records.append(
                    self._authority(
                        identifier=f"authority:prd/glossary.{slug}",
                        authority_class="prd",
                        source=source,
                        section=section,
                        status="Current",
                    )
                )
        return records

    # -- the decision records ---------------------------------------------

    def _adr_trees(self) -> list[tuple[str, Path]]:
        """Every ADR directory in the checkout, labelled, sorted by label.

        Discovered rather than listed. The audit that found
        ``packages/s0ma-mcp/docs/adr`` found it precisely because two
        indexes and one hardcoded pair of paths did not mention it, and a
        provider with the same pair hardcoded would have missed it again.
        """
        trees: list[tuple[str, Path]] = []
        root_tree = self.root / "docs" / "adr"
        if root_tree.is_dir():
            trees.append(("repo", root_tree))
        packages = self.root / "packages"
        if packages.is_dir():
            for package in sorted(packages.iterdir()):
                tree = package / "docs" / "adr"
                if tree.is_dir():
                    trees.append((package.name, tree))
        return trees

    def _adr_records(self) -> list[SourcedRecord]:
        """Every ADR of every tree, with its decision and where it sits.

        The id is tree-qualified — ``authority:adr/repo.ADR-001`` — because
        the bare number is not unique: three trees each number from 001,
        and four numbers are claimed twice over. A flat ``ADR-001`` would
        be three records with different facts under one id, which the
        composition reports as a duplicate rather than resolving. Same
        failure the model already refuses for flat component names, same
        fix.

        The ``index`` fact is three-valued and the three mean different
        things. A path means an index lists this decision. ``unlisted``
        means the tree keeps an index and this decision is not in it —
        somebody forgot. ``none`` means the tree keeps no index at all,
        which is a fact about the tree and not about the decision.
        """
        records: list[SourcedRecord] = []
        for label, tree in self._adr_trees():
            index = self._source(self._relative(tree / "README.md"))
            for source in self._markdown_in(self._relative(tree), "ADR-*.md"):
                name = Path(source.path).name
                found = _ADR_FILE.match(name)
                if found is None:
                    raise DocsProviderError(
                        f"{source.path} is in an ADR tree and its filename "
                        f"carries no number, so it cannot be addressed. ADR "
                        f"filenames are ADR-<number>-<slug>.md."
                    )
                number = found.group("number")
                if index is None:
                    listing = "none"
                elif name in index.text:
                    listing = index.path
                else:
                    listing = "unlisted"
                records.append(
                    self._authority(
                        identifier=f"authority:adr/{label}.ADR-{number}",
                        authority_class="adr",
                        source=source,
                        section=_first_heading(source),
                        status=status_line(
                            _declared_status(source),
                            {"tree": label, "index": listing},
                        ),
                    )
                )
        return records

    # -- the frozen contracts ---------------------------------------------

    def _contract_records(self) -> list[SourcedRecord]:
        """One record per frozen contract, addressed by its file's stem.

        A contract that declares no status is recorded as ``Frozen``: it is
        in ``docs/contracts``, which is what that directory means. A
        contract that *does* declare one is recorded as it declares itself,
        so a contract that has been superseded says so.
        """
        records: list[SourcedRecord] = []
        for source in self._markdown_in(CONTRACTS_DIR, "*.md"):
            stem = Path(source.path).stem
            if stem.lower() == "readme":
                continue
            records.append(
                self._authority(
                    identifier=f"authority:frozen_contract/{stem}",
                    authority_class="frozen_contract",
                    source=source,
                    section=_first_heading(source),
                    status=_declared_status(source) if _has_status(source) else "Frozen",
                )
            )
        return records

    # -- the current language specification --------------------------------

    def _spec_records(self) -> list[SourcedRecord]:
        """The current specification, as one record: ``authority:spec/current``.

        One record, not one per version. The authority comparison falls to
        a single ``spec``-class record when FR-DSL-1 hands it the language
        domain, and two cited spec records at one rank would report a
        conflict instead of an answer. Superseded specifications are
        history; the index addresses what is current and says which version
        that is.
        """
        current: tuple[tuple[int, ...], _Source] | None = None
        for source in self._markdown_in(SPEC_DIR, "s0ma-dsl-spec-v*.md"):
            found = _SPEC_FILE.match(Path(source.path).stem)
            if found is None:
                continue
            version = tuple(int(part) for part in found.group("version").split("."))
            if current is None or version > current[0]:
                current = (version, source)
        if current is None:
            return []
        version_text = ".".join(str(part) for part in current[0])
        return [
            self._authority(
                identifier="authority:spec/current",
                authority_class="spec",
                source=current[1],
                section=_first_heading(current[1]),
                status=status_line("Current", {"version": version_text}),
            )
        ]

    # -- the release identity ---------------------------------------------

    def _release_records(self) -> list[SourcedRecord]:
        """What release this checkout describes, from the one changelog."""
        source = self._source(CHANGELOG)
        if source is None:
            return []
        released: tuple[str, str] | None = None
        unreleased = "absent"
        section = ""
        for line in source.lines:
            found = _RELEASE.match(line)
            if found is None:
                continue
            name = found.group("name")
            if name.lower() == "unreleased":
                unreleased = "present"
                continue
            if released is None:
                released = (name, found.group("date") or "")
                section = line.lstrip("#").strip()
        if released is None:
            return []
        facts = {"version": released[0], "unreleased": unreleased}
        if released[1]:
            facts["date"] = released[1]
        return [
            self._authority(
                identifier="authority:declared/release",
                authority_class="declared",
                source=source,
                section=section,
                status=status_line("Released", facts),
            )
        ]

    # -- the distributions -------------------------------------------------

    def _package_records(self) -> list[SourcedRecord]:
        """One record per distribution: its version, and what it depends on.

        A stopgap, recorded as one. ``@1`` has no record type for a
        distribution, so the version and the in-workspace dependency
        direction ride in the status field's fact grammar rather than in
        fields of their own. They belong in the composed graph either way:
        INV-4's lockstep claim and INV-6's direction claim are checkable
        only against these, and a build that cannot see them cannot check
        either.

        **D6 landed the architecture §7.7 package inventory beside this**,
        as the ``package_inventory`` derived source (ADR-013 §8). It does
        not replace these records: an authority record is what a *document*
        may cite, and a derived source is what a *rendered table* is built
        from. What D6 did remove is the second reading — both now come from
        :func:`package_facts`, so the status grammar and the rendered table
        cannot disagree about a version. Whether the stopgap retires once
        something else carries the lockstep claim is a Phase D close-out
        question, not this milestone's.
        """
        records: list[SourcedRecord] = []
        for item in package_facts(self.root):
            source = self._source(item.source)
            if source is None:  # pragma: no cover - package_facts just read it
                continue
            records.append(
                self._authority(
                    identifier=f"authority:declared/package.{item.distribution}",
                    authority_class="declared",
                    source=source,
                    section="[project]",
                    status=status_line(
                        "Declared",
                        {
                            "version": item.version,
                            "depends": ",".join(item.depends_on)
                            if item.depends_on
                            else "none",
                        },
                    ),
                )
            )
        return records


# ---------------------------------------------------------------------------
# Small readings that need no provider state
# ---------------------------------------------------------------------------


def _has_status(source: _Source) -> bool:
    """Does ``source`` declare a ``**Status:**`` line at all?"""
    return any(_STATUS.match(line) for line in source.lines)


def _header_cell(lines: Iterable[str], label: str) -> str:
    """The value of ``| **<label>** | ... |`` in a document's header table."""
    pattern = re.compile(_HEADER_ROW.format(label=re.escape(label)))
    for line in lines:
        found = pattern.match(line)
        if found is not None:
            return found.group("value").strip()
    return ""


def _prd_identity(source: _Source) -> tuple[str, str]:
    """The PRD's own ``(status word, document version)`` from its header.

    Both come from labelled rows of the header table — a two-column table
    of names and values, not prose — and both are reduced to their first
    token. "Living document — canonical alignment reference …" is
    ``Living``, and "1.9 (2026-08-27)" is ``1.9``; the rest of each cell
    stays where it was written.
    """
    lines = source.lines
    word = _WORD.search(_header_cell(lines, "Status"))
    status = UNKNOWN_DECISION
    if word is not None:
        status = DECISION_WORDS.get(word.group(0).lower(), UNKNOWN_DECISION)
    version = _header_cell(lines, "Version").partition(" ")[0].strip()
    return (status, version or "unknown")


@dataclass(frozen=True)
class PackageFacts:
    """One distribution the workspace ships: identity, version, direction.

    The three facts architecture §7.7 asks a package inventory for, plus
    the file they were read from so a caller that needs a digest can hash
    the same file rather than a second one.

    ``depends_on`` holds only *in-workspace* dependencies, sorted.
    ``fastapi`` and ``lark`` are facts about a build environment; ``s0ma-mcp
    → s0ma-dsl → s0ma-core`` is the direction INV-6 names, and it is the
    only one this reading has any business asserting.
    """

    distribution: str
    version: str
    depends_on: tuple[str, ...]
    source: str


def package_facts(root: Path) -> tuple[PackageFacts, ...]:
    """Every distribution under ``packages/``, sorted by name. One reading.

    Two consumers and one read of each ``pyproject.toml``: the authority
    records of :meth:`RepoProvider._package_records`, which put the version
    and the dependency direction into the composed graph, and D6's
    ``package_inventory`` derived source, which renders them as a table.
    Before D6 the second did not exist; when it arrived it read the same
    four files a second time, and two readings of one file are how a
    version in a rendered table drifts from a version in a record with
    nobody at fault. There is one reading, and this is it.

    A workspace with no ``packages/`` directory reads as empty rather than
    as an error — the function describes a checkout, and a checkout that is
    not this one is not a defect.
    """
    packages = root / "packages"
    if not packages.is_dir():
        return ()
    read: list[tuple[str, str, tuple[str, ...], str]] = []
    names: set[str] = set()
    for package in sorted(packages.iterdir()):
        path = package / "pyproject.toml"
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        name, version, requires = _project_metadata(
            _Source(path=relative, text=text, digest=_digest_of(text))
        )
        if not name:
            continue
        names.add(name)
        read.append((name, version, requires, relative))
    return tuple(
        PackageFacts(
            distribution=name,
            version=version,
            depends_on=tuple(
                sorted({item for item in requires if item in names and item != name})
            ),
            source=relative,
        )
        for name, version, requires, relative in sorted(read)
    )


def _project_metadata(source: _Source) -> tuple[str, str, tuple[str, ...]]:
    """``(name, version, dependency names)`` from one ``pyproject.toml``.

    A structural read: three keys of the ``[project]`` table, with the
    distribution name taken off the front of each dependency specifier.
    Nothing else in the file is looked at, and a workspace root that
    declares no project reads as empty rather than as an error.
    """
    try:
        document = tomllib.loads(source.text)
    except tomllib.TOMLDecodeError as error:
        raise DocsProviderError(f"{source.path} is not readable as TOML: {error}") from error
    project = document.get("project")
    if not isinstance(project, dict):
        return ("", "", ())
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return ("", "", ())
    raw = project.get("dependencies")
    requires: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, str):
                continue
            found = _DIST.match(item)
            if found is not None:
                requires.append(found.group("name"))
    return (name, version, tuple(requires))
