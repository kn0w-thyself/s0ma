#!/usr/bin/env python3
"""Authored-lines guard — the ``authored-lines`` stage.

The five authored fields of a ``.s0ma`` declaration — ``intent``,
``guarantees``, ``invariants``, ``schema`` and ``forbids`` — are what a reader,
person or agent, learns a piece of code by: what it is for, what it promises,
what it never does. They ship inside the self-model and outlive every planning
document, so each line has to stand on its own. A line that leans on a
milestone id, a run, a plan, a date or a ruling points its reader at a record
they cannot open, and it goes stale the day that record is filed away. This
stage refuses such lines.

Two tables decide, and nothing else does:

* EPHEMERAL — the forms refused: a milestone or decision id, a run or a round
  by its id, a plan or review by name, a plan's clause shaped like a section,
  a date, a ruling or a person.
* ALLOWED_FORMS — the forms that are durable because each names a record that
  ships with the repository: a PRD id, an invariant id, an ADR number, a
  contract revision, a specification section. An allowed form is not merely
  tolerated; it must resolve against the file that defines it, so a reference
  to a requirement that was renumbered, or never existed, is refused as well.

A line that matches neither table is accepted: this gate is not a style
checker. Allowed forms are taken out of a line before the ephemeral rows are
matched, so ``FR-DSL-6`` is never read as the id ``DSL-6`` and ``INV-3`` never
as a decision id. The one row matched before them is the clause row, so that
``plan §3.6`` is refused as a plan's clause instead of being resolved as a
section of the language specification.

What is read, and how:

* Every TRACKED ``.s0ma`` file under TREES (``git ls-files``, so an untracked
  file is invisible, as every other corpus gate treats it).
* Each file is split into declarations by the parser's own splitter
  (``s0ma_dsl.parser.s0ma_parser._split_declarations``). Where a field starts
  and ends, what a ``|`` block scalar or a block list holds, and that the code
  after ``---`` is not a field are the parser's decisions; nothing here reads
  the grammar a second way.
* The fields read on a declaration are the field matrix's authored fields
  (``s0ma_dsl.semantic_state``: ``authored_field_names`` and
  ``semantic_source_field``) intersected with FIELDS, so a field the matrix
  does not list for a declaration kind is never read and the matrix is never
  copied. The splitter names ``doc-ref`` and ``doc-guide`` declarations
  ``doc_ref`` and ``doc_guide``, the matrix's own keys, so their ``intent``
  lines are read like every other.
* One authored line is one field, however many physical lines its value
  spans. A refusal names the line the field starts on; whitespace inside a
  value is read as single spaces, so a phrase broken across two physical
  lines is still the phrase.
* The registrations written in Python are read too: every TRACKED ``.py``
  file under a package's ``src/`` tree (``packages/*/src/``), any ``_built``
  directory left out because it is the build output of the ``.s0ma`` sources
  read above. Each file is parsed with ``ast``, never imported, as
  ``scripts/check_version_refs.py`` reads ``__version__``. A line is a value passed as one of FIELDS, by keyword, to
  a call named in CALLS (``@component``, ``ComponentSpec``, ``Contract``):
  a string literal, an implicit concatenation of literals (one constant to
  ``ast``), or a list or tuple of string literals, joined with single spaces
  into one line as a block list is one field. Any other value — an f-string,
  a name, a call, an attribute — is made somewhere else, not written at the
  call, so it is not read, and the summary counts it. A refusal names the
  line the keyword starts on and the registration as ``<call>:<name>``: the
  call's own ``name=``, the enclosing registration's for a ``Contract``
  passed to one, or else the decorated definition's.
* A section, ``§n.n``, resolves against the specification the line's project
  is written against: the core specification for a line under
  ``packages/s0ma-core/src/``, the language specification for every other.

Detection is deliberately broad where the planning record's own shapes are
broad — an id is any capital prefix and a number — and narrowing happens
through the explicit ALLOWLIST, not through a cleverer pattern: a product term
that is also a planning word (the migration tool's dry-run *plan*, the
feedback journey's *review* step) becomes a recorded decision with a written
justification, pinned to the line it covers, rather than a silent exemption.
Two token tables are data instead of allowlist entries because they are about
a token wherever it appears, not about one line: NOT_IDS (the names of
standards, which are shaped like an id) and RUN_WORDS (a run or a round is one
of the planning record's words for one, so ``column-0`` and ``utf-8`` are not
runs).

Anti-vacuity: every refusal is a line the matchers found, so a reader that
reads nothing reports nothing and would pass forever. A scan that reads fewer
than MINIMUM_AUTHORED_LINES authored lines in the ``.s0ma`` files, or fewer
than MINIMUM_PYTHON_LINES in the registrations written in Python, fails, and
a tree in TREES holding no tracked ``.s0ma`` file is an error, as
``scripts/check_links.py`` refuses a linkless scan. The allowed-form half
needs no floor of its own: an allowed form whose pattern stopped matching
would fall through to the id row, which refuses it, so that half fails
closed.

Usage (no arguments, no network, deterministic):

    uv run python scripts/check_authored_lines.py
    uv run python scripts/check.py --only authored-lines
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.errors import S0maParseError
from s0ma_dsl.parser.s0ma_parser import _BLOCK_SCALAR_SENTINEL, _split_declarations
from s0ma_dsl.semantic_state import (
    FIELD_CLASSIFICATIONS,
    authored_field_names,
    semantic_source_field,
)

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent

#: The trees whose ``.s0ma`` sources are read: the two self-hosted packages,
#: the documentation application, the language package's derived-docs
#: generators, the language package's test fixtures, and the spike fixtures
#: under ``scripts/spikes``. Each ships to a reader or teaches one: a fixture
#: is the first example of the language a contributor opens, and a spike's
#: fixture is an example of it in use.
TREES: tuple[str, ...] = (
    "packages/s0ma-mcp/s0ma_src",
    "packages/s0ma-studi0/s0ma_src",
    "docs/s0ma_src",
    "packages/s0ma-dsl/docs/_generators",
    "packages/s0ma-dsl/tests/fixtures",
    "scripts/spikes",
)

#: Trees that a checkout may lack without that being an error. The public
#: export withholds the spike directory whole (its rules are in
#: ``scripts/public_export.toml``), so a tree built by it carries no spike
#: fixture at all; where the fixtures are present they are read like any
#: other tree's. A core tree that loses its last ``.s0ma`` file is still the
#: loud error below, and the floor on the line count still guards the scan.
OPTIONAL_TREES: frozenset[str] = frozenset({"scripts/spikes"})

#: The authored fields this rule covers, as the field matrix names them. Read
#: only where the matrix lets a person write them on a declaration kind.
FIELDS: tuple[str, ...] = ("intent", "guarantees", "invariants", "schema", "forbids")

#: The registration calls whose keyword arguments are authored lines written
#: in Python: the decorator and the two records the runtime registers, by the
#: name they are called with (an attribute call such as ``s0ma.component(...)``
#: by its attribute). A ``Contract`` carries no name of its own; it belongs to
#: the registration it is passed to.
CALLS: tuple[str, ...] = ("component", "ComponentSpec", "Contract")

#: The core package's sources. A section a line there cites is a section of
#: the core specification, the one that project is written against.
CORE_SOURCES = "packages/s0ma-core/src/"

#: A section number as the specifications write one: ``4.14.5``, ``4.4a.6``.
_SECTION = r"\d+[a-z]?(?:\.\d+[a-z]?)*"

#: The planning record's words for a run or a round. A run id is one of them,
#: a hyphen and a number (``pilot-01``, ``feedback-5.5``). Matching the word,
#: not any lowercase word, is what keeps ``column-0``, ``utf-8`` and
#: ``exit-code-3`` out; a new kind of run is one word added here.
RUN_WORDS: tuple[str, ...] = (
    "pilot",
    "feedback",
    "bench",
    "round",
    "run",
    "spike",
    "trial",
    "phase",
    "wave",
    "sprint",
)

#: The names of standards, which are shaped like a decision id and are not
#: one. Taken out of a line before the id row is matched, wherever they occur.
NOT_IDS: tuple[str, ...] = (
    "UTF-8",
    "UTF-16",
    "UTF-32",
    "SHA-1",
    "SHA-256",
    "SHA-512",
)


@dataclass(frozen=True)
class Ephemeral:
    """One row of the refused table: a form that leans on the planning record.

    ``key`` is the label a refusal prints beside the matched text, ``form`` the
    row as a reader recognises it, and ``refused`` an example the row refuses
    (the tests plant every one). ``first`` marks the row matched before the
    allowed forms are taken out of the line.
    """

    key: str
    form: str
    pattern: re.Pattern[str]
    refused: str
    first: bool = False


#: The forms the stage refuses, in the authored fields only.
EPHEMERAL: tuple[Ephemeral, ...] = (
    Ephemeral(
        "id",
        "a milestone or decision id",
        # A capital letter, or a short capital prefix and a hyphen, then digits
        # and an optional letter, with any number of hyphenated prefixes in
        # front (M7, G3c, M02, D-11, FD-13, CRIT-3, POST-4c, DSL-M2, F-M3-1),
        # or the lowercase batch id (batch-01a). A prefix of several capitals
        # needs its hyphen, which is what keeps HTML5 out.
        re.compile(
            r"(?<![\w.])(?:"
            r"(?:[A-Z][A-Z0-9]{0,5}-)*(?:[A-Z]{2,6}-|[A-Z]-?)\d+[a-z]?(?:-\d+[a-z]?)*"
            r"|[Bb]atch-\d+[a-z]?"
            r")(?![\w-])"
        ),
        "pinned by M5 acceptance",
    ),
    Ephemeral(
        "run id",
        "a run or a round by its id",
        re.compile(
            rf"(?<![\w.])(?:{'|'.join(RUN_WORDS)})-\d+(?:\.\d+)*[a-z]?(?![\w-])",
            re.IGNORECASE,
        ),
        "pilot-01 saw four sessions shell out",
    ),
    Ephemeral(
        "planning word",
        "a plan or review by name",
        re.compile(
            r"\bplans/|\b(?:plan|milestone|wave|sprint|review|audit|handoff|hand-off)s?\b",
            re.IGNORECASE,
        ),
        "the ops rule rides here per the plan's sequencing note",
    ),
    Ephemeral(
        "plan clause",
        "a plan's clause shaped like a section",
        re.compile(
            rf"\bplan(?:'s)?\s+§\s?{_SECTION}|§\s?{_SECTION}\s+fact\s+\d+",
            re.IGNORECASE,
        ),
        "§1.2 fact 15 is the caveat",
        first=True,
    ),
    Ephemeral(
        "date",
        "a date",
        re.compile(r"\b20\d\d-[01]\d-[0-3]\d\b"),
        "cut on 2026-08-30",
    ),
    Ephemeral(
        "ruling",
        "a ruling or a person",
        # The planning record names its people by role: a ruling is the
        # owner's or the orchestrator's, and a person is one of them deciding
        # or asking. "owner" and "decision" alone are product words (a
        # module's owner, the decision a cell records) and are not matched.
        re.compile(
            r"\b(?:owner|orchestrator)(?:'s)?[- ](?:rulings?|ruled|decisions?|decided"
            r"|ratified|ratification|approved|approval|accepted|call)\b"
            r"|\b(?:ruled|ratified|decided|approved|accepted)\s+by\s+the\s+(?:owner|orchestrator)\b"
            r"|\bper\s+the\s+(?:owner|orchestrator)\b"
            r"|\bthe\s+(?:owner|orchestrator)\s+(?:asked|ruled|decided|ratified|approved"
            r"|accepted|wants|wanted|chose|prefers|preferred|said)\b",
            re.IGNORECASE,
        ),
        "owner-ratified, ADR-001 amended",
    ),
)


@dataclass(frozen=True)
class AllowedForm:
    """One row of the allowed table: a durable form and where it must resolve."""

    key: str
    form: str
    pattern: re.Pattern[str]
    resolves_against: str


#: The records the allowed forms resolve against. A specification is read at
#: its newest version, the versions compared as numbers.
PRD = "references/s0ma-prd.md"
CORE_SPEC_PREFIX = "packages/s0ma-core/docs/s0ma-core-spec-v"
DSL_SPEC_PREFIX = "packages/s0ma-dsl/docs/s0ma-dsl-spec-v"
ADR_DIRECTORIES: tuple[str, ...] = (
    "docs/adr",
    "packages/s0ma-mcp/docs/adr",
    "packages/s0ma-dsl/docs/adr",
)
CONTRACT = "docs/contracts/0.14.0-schema-and-surface-budget.md"
CONTRACT_REVISION_LOG = "10.5"

_INV_CORE_RE = re.compile(r"(?<![\w.-])INV-CORE-\d+(?![\w-])")
_INV_RE = re.compile(r"(?<![\w.-])INV-\d+(?![\w-])")
_PRD_RE = re.compile(
    r"(?<![\w.-])(?:FR-(?:[A-Z][A-Z0-9]*-)*\d+[a-z]?|NFR-\d+|P-\d+|M-\d+)(?![\w-])"
)

#: The forms a line may cite, because each names a record that ships with the
#: repository. Matched in this order, the narrower form first (``INV-CORE-n``
#: before ``INV-n``), and each must resolve.
ALLOWED_FORMS: tuple[AllowedForm, ...] = (
    AllowedForm(
        "inv-core",
        "INV-CORE-n",
        _INV_CORE_RE,
        f"heading of the newest {CORE_SPEC_PREFIX}*.md",
    ),
    AllowedForm(
        "inv",
        "INV-n",
        _INV_RE,
        f"heading, anchor or definition item in the invariants section of {PRD}",
    ),
    AllowedForm(
        "prd",
        "FR-…, NFR-n, P-n, M-n",
        _PRD_RE,
        f"heading, anchor, definition item or table row in {PRD}",
    ),
    AllowedForm(
        "adr",
        "ADR-nnn",
        re.compile(r"(?<![\w.-])ADR-\d{3,}(?![\w-])"),
        f"record named for the number under {', '.join(d + '/' for d in ADR_DIRECTORIES)}",
    ),
    AllowedForm(
        "revision",
        "Rn",
        re.compile(r"(?<![\w.-])R\d+(?![\w-])"),
        f"row of the revision log, §{CONTRACT_REVISION_LOG} of {CONTRACT}",
    ),
    AllowedForm(
        "section",
        "§n.n",
        re.compile(rf"§\s?(?P<number>{_SECTION})(?!\w)"),
        f"heading of the newest {DSL_SPEC_PREFIX}*.md, by the anchor rule of"
        f" scripts/check_links.py",
    ),
)


@dataclass(frozen=True)
class Exempt:
    """One matched form a line deliberately keeps.

    The only reason that qualifies is that the matched word is the product's
    own term, not the planning record's — the dry-run plan a tool produces, the
    review step of a journey — and ``why`` must say which. ``form`` is the
    matched text (compared without case); ``on_line_containing`` pins the
    exemption to the authored line that justifies it, read with its
    whitespace collapsed, so rewording that line retires the entry and it is
    reported as stale rather than quietly outliving its reason.
    """

    path: str
    form: str
    on_line_containing: str
    why: str


#: Deliberately kept forms: product terms that share a word with the
#: planning record. One entry per justified line.
ALLOWLIST: tuple[Exempt, ...] = (
    Exempt(
        "packages/s0ma-mcp/s0ma_src/prompts.s0ma",
        "review",
        "the prepare-review-approve path they control",
        "the feedback journey's own steps (prepare, review, approve) - a product term",
    ),
    Exempt(
        "packages/s0ma-mcp/s0ma_src/prompts.s0ma",
        "plan",
        "migrate_ext dry-run plan, present, apply",
        "the dry-run plan migrate_ext produces before it applies - a product term",
    ),
    Exempt(
        "packages/s0ma-mcp/s0ma_src/prompts.s0ma",
        "plan",
        "migrate_ext dry-run, present the plan, apply",
        "the dry-run plan migrate_ext produces, which the agent presents - a product term",
    ),
    Exempt(
        "packages/s0ma-mcp/s0ma_src/tools.s0ma",
        "review",
        "the review step of the feedback journey",
        "the review step of the feedback journey (prepare, review, approve) - a product term",
    ),
    Exempt(
        "packages/s0ma-core/src/s0ma/_bootstrap.py",
        "audit",
        "for audit logging and rollback reference",
        "the audit log a lifecycle event is recorded for - a product term",
    ),
)

#: Anti-vacuity floor. The five trees carried 1,239 authored lines when this
#: floor was set (243 of them ``none``), 791 of them in the language package's
#: fixtures. 500 sits far below anything rewording or ordinary fixture churn
#: can reach, and above the 448 the four smaller trees hold between them, so a
#: run rooted somewhere else, a reader that lost the fixtures, or a field set
#: that no longer meets the matrix cannot report PASS. The spike fixtures, read
#: since as a sixth tree, add 15, and the five smaller trees' 463 still sit
#: below it. Genuinely retiring that many authored lines is a deliberate edit
#: here, not a quietly weaker gate.
MINIMUM_AUTHORED_LINES = 500

#: The second floor, for the Python reader. The packages carried 260
#: Python-authored lines when this floor was set, all of them in two: 183 in
#: the language package's ``@component`` registrations, 77 in core's (61
#: ``ComponentSpec`` intents and 16 ``Contract`` invariants lists). 200 sits
#: above the 183 the language package holds alone, so a reader that lost core
#: cannot report PASS, and far above core's 77, so a reader that lost the
#: language package cannot either, with 60 lines of headroom for rewording.
#: Genuinely retiring that many registrations is a deliberate edit here, not
#: a quietly weaker gate.
MINIMUM_PYTHON_LINES = 200


@dataclass(frozen=True)
class AuthoredLine:
    """One authored field of one declaration, as the splitter delimits it."""

    path: str
    lineno: int
    field: str
    declaration: str
    text: str


@dataclass
class Finding:
    """What one authored line matched: refused forms and allowed-form uses."""

    line: AuthoredLine
    refused: list[tuple[Ephemeral, str]]
    unresolved: list[tuple[AllowedForm, str]]


@dataclass(frozen=True)
class Sources:
    """The records the allowed forms resolve against, read once per run."""

    prd_ids: frozenset[str]
    invariants: frozenset[str]
    core_invariants: frozenset[str]
    adrs: frozenset[str]
    revisions: frozenset[str]
    spec_anchors: tuple[str, ...]
    core_spec_anchors: tuple[str, ...]


# ---------------------------------------------------------------------------
# The heading and anchor rules, owned by scripts/check_links.py
# ---------------------------------------------------------------------------


def _links() -> ModuleType:
    """``scripts/check_links.py``, for the heading, fence and anchor rules it owns.

    Loaded by path, and registered in ``sys.modules`` before execution because
    ``@dataclass`` resolves a class's module through it.
    """
    name = "s0ma_check_authored_lines_links"
    loaded = sys.modules.get(name)
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name("check_links.py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the sibling is missing
        raise ImportError("scripts/check_links.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _headings(text: str) -> list[tuple[int, str]]:
    """``(level, title)`` for every heading outside a fenced block, in order."""
    links = _links()
    found: list[tuple[int, str]] = []
    for _lineno, line in links._outside_fences(text.splitlines()):
        match = links._HEADING_RE.match(line)
        if match:
            found.append((len(match.group("hashes")), str(match.group("title"))))
    return found


def _section_lines(text: str, starts: re.Pattern[str]) -> list[str]:
    """The lines under the first heading whose title *starts* matches.

    The section runs to the next heading of the same or a higher level, and
    fenced blocks are left out, as ``scripts/check_links.py`` leaves them out.
    """
    links = _links()
    lines: list[str] = []
    level: int | None = None
    for _lineno, line in links._outside_fences(text.splitlines()):
        match = links._HEADING_RE.match(line)
        if match:
            depth = len(match.group("hashes"))
            if level is not None and depth <= level:
                break
            if level is None and starts.search(str(match.group("title"))):
                level = depth
                continue
        if level is not None:
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# The records allowed forms resolve against
# ---------------------------------------------------------------------------

#: Every id shape the PRD defines, for reading what its headings, anchors and
#: definition items carry.
_PRD_ID_RE = re.compile(
    "|".join(pattern.pattern for pattern in (_INV_CORE_RE, _INV_RE, _PRD_RE))
)
#: A definition item: a list item whose text opens with the id in bold.
_DEFINITION_ITEM_RE = re.compile(r"^\s*[-*+]\s+\*\*(?P<head>[^*]+)")
#: A table row whose first cell is the id, bold or not: the PRD tables its
#: success metrics (``| M-1 | ... |``) instead of listing them.
_TABLE_ROW_RE = re.compile(r"^\|\s*(?:\*\*)?(?P<head>[^|*]+?)(?:\*\*)?\s*\|")
_HTML_ANCHOR_RE = re.compile(
    r"""<a\s[^>]*\b(?:id|name)\s*=\s*["'](?P<name>[^"']+)["']""", re.IGNORECASE
)
_REVISION_ROW_RE = re.compile(r"^\|\s*(?P<revision>R\d+)\s*\|")
_ADR_FILE_RE = re.compile(r"^(?P<adr>ADR-\d{3,})(?!\d)")


def _carried(lines: list[str]) -> set[str]:
    """Every id a heading, an anchor, a definition item or a table row in *lines* carries."""
    links = _links()
    ids: set[str] = set()
    for line in lines:
        heading = links._HEADING_RE.match(line)
        if heading:
            ids.update(match.group() for match in _PRD_ID_RE.finditer(heading.group("title")))
        for anchor in _HTML_ANCHOR_RE.finditer(line):
            if _PRD_ID_RE.fullmatch(anchor.group("name")):
                ids.add(anchor.group("name"))
        item = _DEFINITION_ITEM_RE.match(line)
        if item:
            head = _PRD_ID_RE.match(item.group("head").strip())
            if head:
                ids.add(head.group())
        row = _TABLE_ROW_RE.match(line)
        if row and _PRD_ID_RE.fullmatch(row.group("head").strip()):
            ids.add(row.group("head").strip())
    return ids


def _newest(tracked: frozenset[str], prefix: str) -> str | None:
    """The tracked ``<prefix>X.Y.Z.md`` with the highest version, compared as numbers."""
    best: tuple[tuple[int, ...], str] | None = None
    for rel in tracked:
        if not (rel.startswith(prefix) and rel.endswith(".md")):
            continue
        version = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", rel[len(prefix) : -len(".md")])
        if version is None:
            continue
        key = tuple(int(part) for part in version.groups())
        if best is None or key > best[0]:
            best = (key, rel)
    return best[1] if best else None


def _read(root: Path, tracked: frozenset[str], rel: str | None) -> str:
    """The text of a tracked file, or nothing when it is absent or untracked."""
    if rel is None or rel not in tracked or not (root / rel).is_file():
        return ""
    return (root / rel).read_text(encoding="utf-8")


def load_sources(root: Path, tracked: frozenset[str]) -> Sources:
    """Read every record the allowed forms resolve against."""
    prd = _read(root, tracked, PRD)
    prd_lines = [line for _n, line in _links()._outside_fences(prd.splitlines())]
    invariants = _section_lines(prd, re.compile(r"\bInvariants\b"))
    core = _read(root, tracked, _newest(tracked, CORE_SPEC_PREFIX))
    contract = _read(root, tracked, CONTRACT)
    log = _section_lines(contract, re.compile(rf"^{re.escape(CONTRACT_REVISION_LOG)}\b"))
    adrs: set[str] = set()
    for rel in tracked:
        directory, _slash, name = rel.rpartition("/")
        record = _ADR_FILE_RE.match(name) if directory in ADR_DIRECTORIES else None
        if record:
            adrs.add(record.group("adr"))
    revisions: set[str] = set()
    for line in log:
        row = _REVISION_ROW_RE.match(line)
        if row:
            revisions.add(row.group("revision"))
    anchors: list[str] = _links().document_anchors(
        _read(root, tracked, _newest(tracked, DSL_SPEC_PREFIX))
    )
    return Sources(
        prd_ids=frozenset(
            name for name in _carried(prd_lines) if _PRD_RE.fullmatch(name)
        ),
        invariants=frozenset(
            name for name in _carried(invariants) if _INV_RE.fullmatch(name)
        ),
        core_invariants=frozenset(
            match.group()
            for _level, title in _headings(core)
            for match in _INV_CORE_RE.finditer(title)
        ),
        adrs=frozenset(adrs),
        revisions=frozenset(revisions),
        spec_anchors=tuple(anchors),
        core_spec_anchors=tuple(_links().document_anchors(core)),
    )


def resolves(
    form: AllowedForm, match: re.Match[str], sources: Sources, *, core: bool = False
) -> bool:
    """True when the record *match* names exists, by *form*'s rule.

    *core* marks a line under CORE_SOURCES, whose sections are the core
    specification's.
    """
    text = match.group()
    if form.key == "inv-core":
        return text in sources.core_invariants
    if form.key == "inv":
        return text in sources.invariants
    if form.key == "prd":
        return text in sources.prd_ids
    if form.key == "adr":
        return text in sources.adrs
    if form.key == "revision":
        return text in sources.revisions
    if form.key == "section":
        slug: str = _links().slugify(match.group("number"))
        anchors = sources.core_spec_anchors if core else sources.spec_anchors
        return any(anchor == slug or anchor.startswith(f"{slug}-") for anchor in anchors)
    raise ValueError(f"no resolution rule for allowed form {form.key!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Reading the authored lines
# ---------------------------------------------------------------------------


@cache
def fields_read(kind: str) -> frozenset[str]:
    """The FIELDS a person may write on *kind*, in authored spelling, per the matrix."""
    if kind not in FIELD_CLASSIFICATIONS:
        return frozenset()
    rows = FIELD_CLASSIFICATIONS[kind]
    wanted = {semantic_source_field(kind, field) for field in FIELDS if field in rows}
    return authored_field_names(kind) & wanted


def tracked_files(root: Path) -> frozenset[str]:
    """Every path git tracks under *root*: ``scripts/check_links.py``'s universe."""
    tracked: frozenset[str] = _links().tracked_files(root)
    return tracked


def authored_lines(root: Path, rel: str) -> list[AuthoredLine]:
    """Every authored line of the five fields in the ``.s0ma`` file *rel*.

    Raises ``S0maParseError`` when the parser's splitter refuses the file.
    """
    source = (root / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    found: list[AuthoredLine] = []
    for declaration in _split_declarations(source, rel):
        wanted = fields_read(declaration.decl_type)
        label = f"{declaration.decl_type.replace('_', '-')}:{declaration.header_names[0]}"
        for field in sorted(wanted, key=lambda name: declaration.field_lines.get(name, 0)):
            if field not in declaration.fields:
                continue
            raw = declaration.fields[field]
            if raw.startswith(_BLOCK_SCALAR_SENTINEL):
                raw = raw[len(_BLOCK_SCALAR_SENTINEL) :]
            found.append(
                AuthoredLine(
                    path=rel,
                    lineno=declaration.field_lines[field],
                    field=field,
                    declaration=label,
                    text=" ".join(raw.split()),
                )
            )
    return found


def is_python_source(rel: str) -> bool:
    """True for a ``.py`` file under ``packages/*/src/`` outside every ``_built`` directory."""
    parts = rel.split("/")
    return (
        rel.endswith(".py")
        and len(parts) > 3
        and parts[0] == "packages"
        and parts[2] == "src"
        and "_built" not in parts
    )


def _call_name(call: ast.Call) -> str | None:
    """The name in CALLS that *call* is made by, or ``None`` for any other call."""
    func = call.func
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr
    else:
        return None
    return name if name in CALLS else None


def _string_keyword(call: ast.Call, keyword: str) -> str | None:
    """The string literal *call* passes as *keyword*, if it passes one."""
    for passed in call.keywords:
        value = passed.value
        if passed.arg == keyword and isinstance(value, ast.Constant):
            if isinstance(value.value, str):
                return value.value
    return None


def _literal(value: ast.expr) -> str | None:
    """The text written at the call, or ``None`` when *value* is made elsewhere.

    A string literal is its text (an implicit concatenation is already one
    constant); a list or tuple whose every element is a string literal is one
    line, its elements joined with single spaces, as a block list is one field.
    """
    if isinstance(value, ast.Constant):
        return value.value if isinstance(value.value, str) else None
    if isinstance(value, (ast.List, ast.Tuple)):
        texts: list[str] = []
        for element in value.elts:
            if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
                return None
            texts.append(element.value)
        return " ".join(texts)
    return None


def python_lines(root: Path, rel: str) -> tuple[list[AuthoredLine], int]:
    """Every Python-authored line in the ``.py`` file *rel*, and the values not read.

    Raises ``SyntaxError`` or ``ValueError`` when the file cannot be read as
    Python source.
    """
    source = (root / rel).read_text(encoding="utf-8")
    with warnings.catch_warnings():
        # This reader is not a linter: an escape sequence in some other string
        # is not its finding, and must not print on the gate's stderr.
        warnings.simplefilter("ignore")
        tree = ast.parse(source, filename=rel)
    found: list[tuple[int, int, AuthoredLine]] = []
    not_read = 0
    decorated: dict[int, str] = {}
    pending: list[tuple[ast.AST, str | None]] = [(tree, None)]
    while pending:
        node, enclosing = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorated.update((id(decorator), node.name) for decorator in node.decorator_list)
        call = _call_name(node) if isinstance(node, ast.Call) else None
        if isinstance(node, ast.Call) and call is not None:
            own = _string_keyword(node, "name")
            if own is not None:
                name = own
            elif call == "Contract" and enclosing is not None:
                name = enclosing
            else:
                name = decorated.get(id(node), "?")
            for passed in node.keywords:
                field = passed.arg
                if field is None or field not in FIELDS:
                    continue
                text = _literal(passed.value)
                if text is None:
                    not_read += 1
                    continue
                line = AuthoredLine(
                    path=rel,
                    lineno=passed.lineno,
                    field=field,
                    declaration=f"{call}:{name}",
                    text=" ".join(text.split()),
                )
                found.append((passed.lineno, passed.col_offset, line))
            if own is not None and call != "Contract":
                enclosing = own
        pending.extend((child, enclosing) for child in ast.iter_child_nodes(node))
    ordered = sorted(found, key=lambda hit: (hit[0], hit[1]))
    return [line for _lineno, _column, line in ordered], not_read


def _blank(text: str, match: re.Match[str]) -> str:
    """*text* with *match*'s span replaced by spaces, so no later row sees it."""
    return text[: match.start()] + " " * (match.end() - match.start()) + text[match.end() :]


_NOT_IDS_RE = re.compile(
    rf"(?<![\w.-])(?:{'|'.join(re.escape(name) for name in NOT_IDS)})(?![\w-])"
)


def scan(line: AuthoredLine, sources: Sources) -> tuple[Finding, int]:
    """Match *line* against both tables. Return its finding and the resolved count."""
    text = line.text
    refused: list[tuple[int, Ephemeral, str]] = []
    unresolved: list[tuple[AllowedForm, str]] = []
    resolved = 0
    core = line.path.startswith(CORE_SOURCES)
    for row in EPHEMERAL:
        if row.first:
            for match in list(row.pattern.finditer(text)):
                refused.append((match.start(), row, match.group()))
                text = _blank(text, match)
    for form in ALLOWED_FORMS:
        for match in list(form.pattern.finditer(text)):
            if resolves(form, match, sources, core=core):
                resolved += 1
            else:
                unresolved.append((form, match.group()))
            text = _blank(text, match)
    for match in list(_NOT_IDS_RE.finditer(text)):
        text = _blank(text, match)
    for row in EPHEMERAL:
        if not row.first:
            for match in list(row.pattern.finditer(text)):
                refused.append((match.start(), row, match.group()))
                text = _blank(text, match)
    ordered = [(row, found) for _start, row, found in sorted(refused, key=lambda hit: hit[0])]
    return Finding(line, ordered, unresolved), resolved


def _exempt(
    allowlist: tuple[Exempt, ...], used: set[int], line: AuthoredLine, found: str
) -> bool:
    """True when an *allowlist* entry keeps *found* on *line* (marking it used)."""
    hit = False
    for index, entry in enumerate(allowlist):
        if (
            entry.path == line.path
            and entry.form.casefold() == found.casefold()
            and entry.on_line_containing in line.text
        ):
            used.add(index)
            hit = True
    return hit


def _against(form: AllowedForm, line: AuthoredLine) -> str:
    """The record *form* resolves against for *line*, as a refusal names it."""
    if form.key == "section" and line.path.startswith(CORE_SOURCES):
        return (
            f"heading of the newest {CORE_SPEC_PREFIX}*.md, by the anchor rule of"
            f" scripts/check_links.py"
        )
    return form.resolves_against


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def check(root: Path = ROOT, allowlist: tuple[Exempt, ...] = ALLOWLIST) -> int:
    """Report every authored line that leans on the planning record. Return the count.

    *allowlist* is a parameter for the reason ``scripts/check_version_refs.py``
    gives: the exemption mechanism is testable against a scratch tree only if
    the caller can state which exemptions apply there. The shipped ALLOWLIST
    is the default and the only value the stage ever passes.
    """
    for entry in allowlist:
        in_trees = entry.path.startswith(tuple(f"{tree}/" for tree in TREES))
        if not (in_trees or is_python_source(entry.path)):
            print(
                f"ERROR allowlist entry names a file outside TREES and the Python "
                f"sources: {entry.path}"
            )
            return 1

    try:
        tracked = tracked_files(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR cannot list the tracked files under {root}: {exc}")
        return 1

    files = sorted(
        rel
        for rel in tracked
        if rel.endswith(".s0ma") and rel.startswith(tuple(f"{tree}/" for tree in TREES))
    )
    missing = [tree for tree in TREES if not any(rel.startswith(f"{tree}/") for rel in files)]
    withheld = [tree for tree in missing if tree in OPTIONAL_TREES]
    missing = [tree for tree in missing if tree not in OPTIONAL_TREES]
    for tree in withheld:
        print(f"NOTE no tracked .s0ma file under {tree} - withheld from this checkout; skipped")
    for tree in missing:
        print(
            f"ERROR no tracked .s0ma file under {tree} - the tree moved or emptied; "
            f"update TREES in {Path(__file__).name}"
        )
    if missing:
        return 1

    sources = load_sources(root, tracked)
    errors = 0
    lines: list[AuthoredLine] = []
    for rel in files:
        if not (root / rel).is_file():  # deleted in the work tree, not yet staged
            continue
        try:
            lines.extend(authored_lines(root, rel))
        except S0maParseError as exc:
            print(
                f"ERROR {rel}: the parser's splitter refuses this file ({exc.code} at line "
                f"{exc.line}), so its authored lines cannot be read"
            )
            errors += 1

    python: list[AuthoredLine] = []
    not_read = 0
    for rel in sorted(rel for rel in tracked if is_python_source(rel)):
        if not (root / rel).is_file():  # deleted in the work tree, not yet staged
            continue
        try:
            registered, skipped = python_lines(root, rel)
        except (SyntaxError, ValueError) as exc:
            print(
                f"ERROR {rel}: this file cannot be read as Python source ({exc}), so "
                f"its authored lines cannot be read"
            )
            errors += 1
            continue
        python.extend(registered)
        not_read += skipped

    used: set[int] = set()
    resolved = 0
    allowlisted = 0
    refusals: list[Finding] = []
    unresolved: list[Finding] = []
    for line in [*lines, *python]:
        finding, count = scan(line, sources)
        resolved += count
        kept = finding.refused
        finding.refused = [
            (row, found) for row, found in kept if not _exempt(allowlist, used, line, found)
        ]
        allowlisted += len(kept) - len(finding.refused)
        if finding.refused:
            refusals.append(finding)
        if finding.unresolved:
            unresolved.append(finding)

    for index, entry in enumerate(allowlist):
        if index not in used:
            print(
                f"WARNING stale allowlist entry: {entry.path} {entry.form!r} on a line "
                f"containing {entry.on_line_containing!r} no longer matches anything - "
                f"the line changed; delete the entry."
            )

    for finding in refusals:
        line = finding.line
        forms = ", ".join(
            dict.fromkeys(f"{found!r} ({row.key})" for row, found in finding.refused)
        )
        print(f"VIOLATION {line.path}:{line.lineno}: {line.field} of {line.declaration}: {forms}")
    for finding in unresolved:
        line = finding.line
        for form, found in finding.unresolved:
            print(
                f"UNRESOLVED {line.path}:{line.lineno}: {line.field} of {line.declaration} "
                f"cites {found!r} ({form.form}), and no {_against(form, line)} carries it"
            )

    read = len(lines)
    nones = sum(1 for line in lines if line.text == "none")
    python_read = len(python)
    python_files = len({line.path for line in python})
    counts = (
        f"{read} authored line(s) read ({nones} none) in {len(files)} .s0ma file(s) "
        f"across {len(TREES) - len(withheld)} trees; {python_read} Python-authored line(s) read in "
        f"{python_files} .py file(s) ({not_read} not read: not a literal); "
        f"{resolved} allowed form use(s) resolved; {allowlisted} form(s) allowlisted"
    )
    if refusals:
        print(
            f"\n{len(refusals)} authored line(s) lean on a record their reader cannot "
            f"open. For each one, do exactly one of:\n"
            f"  * reword it to stand alone - say what is true of the code itself, with\n"
            f"    no milestone, run, plan, date or ruling behind it;\n"
            f"  * replace the reference with an allowed form that resolves - a PRD id,\n"
            f"    an invariant id, an ADR number, a contract revision or a section of\n"
            f"    the language specification (ALLOWED_FORMS in {Path(__file__).name});\n"
            f"  * record it in ALLOWLIST at the top of scripts/{Path(__file__).name}\n"
            f"    with a one-line justification, if the matched word is the product's\n"
            f"    own term (the dry-run plan a tool produces, a journey's review step)\n"
            f"    rather than the planning record."
        )
    if unresolved:
        print(
            f"\n{sum(len(f.unresolved) for f in unresolved)} allowed form use(s) resolve "
            f"to nothing. An allowed form is durable only while the record it names\n"
            f"exists: correct the reference to the id as its source defines it, or\n"
            f"reword the line so that it cites no record."
        )
    if refusals or unresolved or errors:
        print(
            f"authored-lines: FAIL - {len(refusals)} line(s) refused, "
            f"{sum(len(f.unresolved) for f in unresolved)} allowed form use(s) unresolved, "
            f"{errors} file(s) unreadable; {counts}"
        )
        return len(refusals) + sum(len(f.unresolved) for f in unresolved) + errors

    # Nothing above this line can fail on a scan that read nothing: every
    # refusal is a line the reader found. A green verdict therefore has to
    # prove the reader still reaches the lines it is meant to police.
    if read < MINIMUM_AUTHORED_LINES:
        print(
            f"\nVACUOUS SCAN: {read} authored line(s) read in {len(files)} .s0ma "
            f"file(s), fewer than the {MINIMUM_AUTHORED_LINES} this repository is\n"
            f"known to carry. Nothing was really checked - this gate only ever reports\n"
            f"what it reads, so a reader that reads nothing passes every time. Either\n"
            f"the run is rooted somewhere else, or TREES / FIELDS in "
            f"{Path(__file__).name}\n"
            f"or the parser's splitter stopped reaching the authored fields. Fix the\n"
            f"reader before trusting a green result; lower MINIMUM_AUTHORED_LINES only\n"
            f"if the trees genuinely shrank."
        )
    # The same proof for the Python reader: a package it stopped reaching would
    # empty it without a single refusal to show for the loss.
    if python_read < MINIMUM_PYTHON_LINES:
        print(
            f"\nVACUOUS SCAN: {python_read} Python-authored line(s) read in "
            f"{python_files} .py file(s), fewer than the {MINIMUM_PYTHON_LINES} this\n"
            f"repository is known to carry. Nothing was really checked - this gate only\n"
            f"ever reports what it reads, so a reader that reads nothing passes every\n"
            f"time. Either the run is rooted somewhere else, or CALLS / FIELDS in "
            f"{Path(__file__).name}\n"
            f"or the Python reader stopped reaching the registrations under\n"
            f"packages/*/src/. Fix the reader before trusting a green result; lower\n"
            f"MINIMUM_PYTHON_LINES only if the registrations genuinely shrank."
        )
    if read < MINIMUM_AUTHORED_LINES or python_read < MINIMUM_PYTHON_LINES:
        return 1

    print(f"authored-lines: PASS - {counts}")
    return 0


def main() -> int:
    # Windows consoles/redirections can default to cp1252, where echoing an
    # authored line (they are full of em-dashes and section signs) would raise
    # UnicodeEncodeError and kill this gate's own reporting. Same guard, and
    # same reason, as scripts/check.py; a subprocess needs its own.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    return 0 if check() == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
