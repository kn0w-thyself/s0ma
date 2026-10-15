"""The quick reference: one page for a person, one document for a program.

Two declared outputs of the documentation application, rendered from one
in-memory value so they cannot disagree:

* :data:`QUICK_REFERENCE_OUTPUT` — a reader-facing page: what the parts of a
  ``.s0ma`` file are, what each line of them means, the commands used most,
  the basic rules, and where to ask for more;
* :data:`QUICK_REFERENCE_MACHINE_OUTPUT` — the same facts as data, for a
  coding agent or a program.

**Three readings meet here, and each is checked against the others.**

1. *The language*, read from the running toolchain and never copied:
   which lines a declaration may carry and whether each must be written
   (:func:`~s0ma_dsl.semantic_state.authored_lines`, the same reading the
   check's own ``UNKNOWN_FIELD`` report uses), the closed sets of words a
   line accepts, and which layer may reach which. :func:`language_facts`.
2. *The composed model*: what each kind of declaration is for, which
   commands, reports, settings and agent tools the product really serves,
   and which documents exist. Everything the page names is resolved against
   it, so a command that was renamed stops the page rather than staying on
   it.
3. *The authored words*, in :data:`QUICK_REFERENCE_SOURCE`: what each line
   says, in plain language, and the sample project every sample is cut
   from. Coverage is held in both directions — a line the language has and
   the words do not describe is refused, and so is a description of a line
   the language does not have.

**The samples are checked before the page is written.** Every ``.s0ma``
file of the sample project is parsed and validated here, in process, at the
strictest mode; one report of any severity refuses both outputs. That is
the half an offline build can do. Building the project, running its tests
and running its example start processes, which SDA-INV-8 keeps out of this
build, so that half lives in the suite (``test_docs_quick_reference.py``)
— the split E2 drew for transcript fixtures, for the same reason.

**The page keeps its own changelog, and cannot forget to.** The authored
file's newest edition pins a digest of each group of language facts
(:func:`fact_pins`). When the language changes, the pins stop matching and
the refusal names the groups that moved, so the edition list is written by
somebody who was told what changed.

**Refusals, not findings.** Everything above raises
:class:`DocsQuickReferenceError`, which the application reports as
``DOC_GATE_VACUOUS`` at the output that was not written: an author cannot be
shown a page that is partly right. The one finding this module makes is the
voice rule (:func:`check_quick_reference_voice`), which is about words and
not about facts.

**Determinism.** No clock, no network, no subprocess, no machine path. The
date on the page is the authored date of its newest edition.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from s0ma_dsl.docs_model.inventories import GENERATED_NOTE, cell
from s0ma_dsl.docs_model.providers import Finding
from s0ma_dsl.docs_model.providers_cli import CHANNEL as CLI_CHANNEL
from s0ma_dsl.docs_model.providers_concepts import (
    DOC_VOICE_VIOLATION,
    FORBIDDEN_IN_AUTHORED_PROSE,
)
from s0ma_dsl.docs_model.providers_config import CHANNEL as CONFIG_CHANNEL
from s0ma_dsl.docs_model.providers_diagnostics import CHANNEL as DIAGNOSTIC_CHANNEL
from s0ma_dsl.docs_model.providers_diagnostics import (
    MATRIX_REGISTRY,
    NOT_APPLICABLE,
    REGISTRY_KEY,
    fact_map,
)
from s0ma_dsl.docs_model.records import DocsModelError
from s0ma_dsl.docs_model.reference_pages import anchor, deep_link
from s0ma_dsl.docs_model.serialize import canonical_json

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from s0ma_dsl.docs_model.providers_cli import CommandInterface
    from s0ma_dsl.docs_model.records import DocsBundle

__all__ = [
    "QUICK_REFERENCE_MACHINE_OUTPUT",
    "QUICK_REFERENCE_OUTPUT",
    "QUICK_REFERENCE_SCHEMA",
    "QUICK_REFERENCE_SOURCE",
    "QUICK_REFERENCE_SOURCE_SCHEMA",
    "ChoiceFact",
    "DocsQuickReferenceError",
    "KindFact",
    "LanguageFacts",
    "LineFact",
    "check_quick_reference_voice",
    "fact_pins",
    "language_facts",
    "quick_reference",
    "quick_reference_source",
    "render_machine",
    "render_readable",
    "sample_files",
]


# ---------------------------------------------------------------------------
# Where things are
# ---------------------------------------------------------------------------

#: The authored words and the sample project, repository-relative. Under
#: ``docs/s0ma_src/`` for ADR-012 §1's reason: it is an authored input the
#: build reads and cannot write back.
QUICK_REFERENCE_SOURCE = "docs/s0ma_src/quick-reference.json"

#: The authored file's own schema. Not the rendered document's: the file is
#: an input to this module, and one version string over both would make a
#: change to either look like a change to both.
QUICK_REFERENCE_SOURCE_SCHEMA = "s0ma-docs-quick-reference@1"

#: The page a person opens, relative to the documentation root. Beside the
#: other generated references, for ADR-012 §2.3 rule B-2: a reader-facing
#: page never lives under ``_generated/``.
QUICK_REFERENCE_OUTPUT = "reference/quick-reference-readable.md"

#: The same facts as data. ``_generated/`` because a program reads it.
QUICK_REFERENCE_MACHINE_OUTPUT = "_generated/quick-reference-machine.json"

#: The schema of the rendered data document.
QUICK_REFERENCE_SCHEMA = "s0ma-quick-reference@1"

#: How far in a line of a description starts. Stated on the page, and read
#: from the parser so the page cannot state another number.
_INDENT_FACT = "field_indent"


class DocsQuickReferenceError(DocsModelError):
    """The quick reference cannot be rendered honestly from what it was handed.

    Raised rather than reported: every condition here would put something
    untrue on a page whose whole claim is that it is checked.
    """


# ---------------------------------------------------------------------------
# Reading 1 — the language
# ---------------------------------------------------------------------------

#: The matrix's three authored classes, in the words the page's own legend
#: is keyed by.
_WRITE_WORDS: Mapping[str, str] = {
    "semantic-required-state": "always",
    "semantic-conditional-state": "when-it-applies",
    "presentation-optional": "optional",
}

#: How the row for a declaration's code may open, by what the table says
#: of it. The words after the opening are the author's: what the table
#: calls conditional is "always, unless" for one kind and "optional" for
#: another, and only a person knows which reads true.
_CODE_OPENINGS: Mapping[str, tuple[str, ...]] = {
    "always": ("Always",),
    "when-it-applies": ("Always, unless", "When it applies", "Optional"),
    "optional": ("Optional",),
}

#: The two things a line may hold in place of an answer, and the legend's
#: word for a line that may hold neither.
_STATES: tuple[str, ...] = ("none", "pending")
_NEITHER = "neither"


@dataclass(frozen=True)
class LineFact:
    """One thing a person writes on one kind of declaration.

    ``kind`` is the matrix's key (``doc_ref``); the word a person types
    (``doc-ref``) is on :class:`KindFact`. ``values`` is the closed set the
    line accepts, empty for a line that takes anything of its type.
    """

    kind: str
    name: str
    place: str
    write: str
    may_be_none: bool
    may_be_pending: bool
    applies: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class KindFact:
    """One kind of declaration, as the language has it."""

    kind: str
    word: str
    first_line: tuple[str, ...]
    lines: tuple[LineFact, ...]
    code: LineFact | None
    worked_out: tuple[str, ...]


@dataclass(frozen=True)
class ChoiceFact:
    """One closed set of words, and the lines that accept it."""

    group: str
    values: tuple[str, ...]
    used_by: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LanguageFacts:
    """Everything this module reads from the language, read once."""

    kinds: tuple[KindFact, ...]
    choices: tuple[ChoiceFact, ...]
    reach: tuple[tuple[str, tuple[str, ...]], ...]
    indent: int
    sources: tuple[str, ...]

    def kind(self, word: str) -> KindFact | None:
        """The kind a person spells ``word``, if the language has one."""
        return next((item for item in self.kinds if item.word == word), None)

    def choice(self, group: str) -> ChoiceFact | None:
        """The closed set named ``group``, if there is one."""
        return next((item for item in self.choices if item.group == group), None)


def _closed_sets() -> tuple[ChoiceFact, ...]:
    """Every closed set of words a line accepts, read from where it is enforced.

    The one table in this module that is knowledge rather than reading:
    *which* line takes *which* set is decided inside the builders that
    parse each line, and nothing publishes it. It is held honest from the
    other side — a line the authored words call a choice and this table
    does not list is refused, and so is the reverse.
    """
    from s0ma_dsl.ast_nodes.enums import (
        VALID_KINDS_FOR_DECLARATION,
        Coupling,
        DeclarationType,
        EvaluatesAt,
        Kind,
        Layer,
        Relation,
        Visibility,
    )
    from s0ma_dsl.codegen.doc_emitter.derived_sources import SUPPORTED_DOC_FORMATS
    from s0ma_dsl.parser.s0ma_parser import VALID_CELL_CATEGORIES, VALID_EXAMPLE_RUNS_IN

    def kinds_of(declaration: DeclarationType) -> tuple[str, ...]:
        allowed = VALID_KINDS_FOR_DECLARATION[declaration]
        return tuple(item.value for item in Kind if item in allowed)

    return (
        ChoiceFact("layer", tuple(item.value for item in Layer), (("module", "layer"),)),
        ChoiceFact("nerve-kind", kinds_of(DeclarationType.NERVE), (("nerve", "kind"),)),
        ChoiceFact("cell-kind", kinds_of(DeclarationType.CELL), (("cell", "kind"),)),
        ChoiceFact(
            "visibility",
            tuple(item.value for item in Visibility),
            (("nerve", "visibility"), ("cell", "visibility"), ("ganglion", "visibility")),
        ),
        ChoiceFact(
            "scale",
            tuple(item.value for item in EvaluatesAt),
            (("nerve", "evaluates_at"), ("ganglion", "scope")),
        ),
        ChoiceFact(
            "relation",
            tuple(item.value for item in Relation if item.is_authored()),
            (("axon", "relation"),),
        ),
        ChoiceFact("coupling", tuple(item.value for item in Coupling), (("axon", "coupling"),)),
        ChoiceFact("category", tuple(sorted(VALID_CELL_CATEGORIES)), (("cell", "category"),)),
        ChoiceFact(
            "format",
            tuple(sorted(SUPPORTED_DOC_FORMATS)),
            (("doc-ref", "format"), ("doc-guide", "format")),
        ),
        ChoiceFact("runs-in", tuple(sorted(VALID_EXAMPLE_RUNS_IN)), (("example", "runs_in"),)),
    )


def language_facts() -> LanguageFacts:
    """What the language accepts, read from the toolchain that enforces it."""
    from s0ma_dsl.ast_nodes.enums import Layer
    from s0ma_dsl.parser import s0ma_parser
    from s0ma_dsl.resolver.dependency import _ALLOWED_TARGET_LAYERS
    from s0ma_dsl.semantic_state import (
        FIELD_CLASSIFICATIONS,
        authored_lines,
        derived_field_names,
    )

    choices = _closed_sets()
    values_of = {
        (kind, line): choice.values for choice in choices for kind, line in choice.used_by
    }

    kinds: list[KindFact] = []
    for kind in FIELD_CLASSIFICATIONS:
        word = kind.replace("_", "-")
        lines: list[LineFact] = []
        first: list[str] = []
        code: LineFact | None = None
        for authored in authored_lines(kind):
            row = authored.classification
            stands_in = authored.field is None or authored.name != _spelling(kind, authored.field)
            fact = LineFact(
                kind=kind,
                name=authored.name,
                place=authored.place,
                write="optional" if row is None else _WRITE_WORDS[row.field_class],
                # A spelling that stands in for another row — ``content:``
                # for a cell's code — has no way to be written as a state.
                may_be_none=bool(row and row.allow_none and not stands_in),
                may_be_pending=bool(row and row.allow_pending and not stands_in),
                applies="" if row is None or row.applicability == "always" else row.applicability,
                values=values_of.get((word, authored.name), ()),
            )
            if authored.place == "first-line":
                first.append(authored.name)
            elif authored.place == "code":
                code = fact
            else:
                lines.append(fact)
        kinds.append(
            KindFact(
                kind=kind,
                word=word,
                first_line=tuple(first),
                lines=tuple(lines),
                code=code,
                worked_out=tuple(sorted(derived_field_names(kind))),
            )
        )

    reach = tuple(
        (
            layer.value,
            tuple(item.value for item in Layer if item in _ALLOWED_TARGET_LAYERS.get(layer, ())),
        )
        for layer in Layer
    )
    return LanguageFacts(
        kinds=tuple(kinds),
        choices=choices,
        reach=reach,
        indent=s0ma_parser._FIELD_INDENT,
        sources=(
            "python:s0ma_dsl.ast_nodes.enums",
            "python:s0ma_dsl.parser.s0ma_parser",
            "python:s0ma_dsl.resolver.dependency",
            "python:s0ma_dsl.semantic_state",
        ),
    )


def _spelling(kind: str, field: str) -> str:
    from s0ma_dsl.semantic_state import semantic_source_field

    return semantic_source_field(kind, field)


def _short(value: Any) -> str:
    """Twelve characters of the digest of ``value``'s canonical form."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:12]


def fact_pins(facts: LanguageFacts, modes: Sequence[str]) -> dict[str, str]:
    """One short digest per group of language facts.

    What the authored file's newest edition pins. A group is one kind's
    lines, one closed set's words, or the strictness ladder — small enough
    that a changed pin tells an author where to look.
    """
    pins: dict[str, str] = {}
    for kind in facts.kinds:
        pins[f"kind:{kind.word}"] = _short(
            {
                "first_line": list(kind.first_line),
                "lines": [
                    [
                        line.name,
                        line.place,
                        line.write,
                        line.may_be_none,
                        line.may_be_pending,
                        list(line.values),
                    ]
                    for line in (*kind.lines, *((kind.code,) if kind.code else ()))
                ],
                "worked_out": list(kind.worked_out),
            }
        )
    for choice in facts.choices:
        pins[f"words:{choice.group}"] = _short(sorted(choice.values))
    pins["layers:reach"] = _short([[layer, list(reached)] for layer, reached in facts.reach])
    pins["modes"] = _short(list(modes))
    return pins


# ---------------------------------------------------------------------------
# Reading 3 — the authored words
# ---------------------------------------------------------------------------

_TEXT = "text"  # a string with something in it
_WORDS = "words"  # a string, which may be empty
_FLAG = "flag"
_NUMBER = "number"


def _each(shape: Any) -> tuple[str, Any]:
    return ("each", shape)


def _maybe(shape: Any) -> tuple[str, Any]:
    return ("maybe", shape)


def _keyed(shape: Any) -> tuple[str, Any]:
    return ("keyed", shape)


_SAMPLE_REF = {"caption": _WORDS, "file": _TEXT, "declaration": _TEXT}
_LINE = {"line": _TEXT, "type": _TEXT, "of": _WORDS, "also": _WORDS, "says": _TEXT}
_LEGEND = {"word": _TEXT, "shown_as": _TEXT, "means": _TEXT}

#: The authored file's shape. Every key is required and no other key is
#: accepted: a file that does not satisfy its own schema cannot be partly
#: believed, and a misspelt key would otherwise be a paragraph that
#: silently never reached the page.
_SHAPE: Mapping[str, Any] = {
    "schema": _TEXT,
    "page": {
        "title": _TEXT,
        "summary": _TEXT,
        "specification": _TEXT,
        "preview_note": _TEXT,
    },
    "orientation": {
        "heading": _TEXT,
        "paragraphs": _each(_TEXT),
        "lead": _TEXT,
        "points": _each({"say": _TEXT, "because": _TEXT}),
    },
    "shape": {
        "heading": _TEXT,
        "sketch": _each(_WORDS),
        "notes": _each(_TEXT),
        "project_lead": _TEXT,
        "project": _each(_WORDS),
        "settings_lead": _TEXT,
        "settings_file": _TEXT,
    },
    "kinds_section": {
        "heading": _TEXT,
        "lead": _TEXT,
        "choosing": _TEXT,
        "columns": {"kind": _TEXT, "when": _TEXT, "in_short": _TEXT, "code": _TEXT},
        "more": _TEXT,
        "code": {
            "none": _TEXT,
            "always": _TEXT,
            "usually": _TEXT,
            "optional": _TEXT,
            "writing": _TEXT,
        },
    },
    "reading": {
        "heading": _TEXT,
        "lead": _TEXT,
        "write_lead": _TEXT,
        "write": _each(_LEGEND),
        "may_lead": _TEXT,
        "may": _each(_LEGEND),
        "holds_lead": _TEXT,
        "means_column": _TEXT,
        "looks_like_column": _TEXT,
        "imports": _TEXT,
        "long_forms": _TEXT,
    },
    "types": _each({"type": _TEXT, "word": _TEXT, "looks_like": _TEXT}),
    "choices_section": {"heading": _TEXT, "reach_column": _TEXT, "reserved": _TEXT},
    "choices": _each(
        {
            "group": _TEXT,
            "title": _TEXT,
            "says": _TEXT,
            "column": _TEXT,
            "looks_like_column": _WORDS,
            "values": _each(
                {"value": _TEXT, "says": _TEXT, "looks_like": _WORDS, "reserved": _FLAG}
            ),
        }
    ),
    "kinds_detail": {
        "heading": _TEXT,
        "lead": _TEXT,
        "columns": {
            "line": _TEXT,
            "write": _TEXT,
            "may": _TEXT,
            "holds": _TEXT,
            "says": _TEXT,
        },
        "code_row": _TEXT,
        "prose_row": _TEXT,
    },
    "kinds": _each(
        {
            "kind": _TEXT,
            "when": _TEXT,
            "first_line": _TEXT,
            "opening": _TEXT,
            "lines": _each(_LINE),
            "code": _maybe({"write": _TEXT, "type": _TEXT, "says": _TEXT}),
            "before_samples": _each(_TEXT),
            "samples": _each(_SAMPLE_REF),
            "after_samples": _each(_TEXT),
        }
    ),
    "commands_section": {"heading": _TEXT, "command_column": _TEXT, "does_column": _TEXT},
    "commands": {
        "lead": _TEXT,
        "first_session": _each({"command": _WORDS, "write": _TEXT, "note": _WORDS}),
        "groups": _each(
            {
                "title": _TEXT,
                "commands": _each({"command": _TEXT, "write": _TEXT, "says": _TEXT}),
            }
        ),
    },
    "modes": {
        "lead": _TEXT,
        "unchanging": _TEXT,
        "only_here": _TEXT,
        "values": _each({"mode": _TEXT, "meant_for": _TEXT, "treats": _TEXT}),
    },
    "modes_columns": {
        "mode": _TEXT,
        "meant_for": _TEXT,
        "treats": _TEXT,
        "refuses": _TEXT,
        "warns": _TEXT,
        "skips": _TEXT,
    },
    "rules_section": {"heading": _TEXT, "reported_as": _TEXT},
    "rules": _each({"rule": _TEXT, "detail": _TEXT, "reports": _each(_TEXT)}),
    "more_section": {"heading": _TEXT},
    "more": {
        "ask_s0ma": {"lead": _TEXT, "says": _TEXT, "commands": _each(_TEXT)},
        "ask_agent": {
            "lead": _TEXT,
            "says": _TEXT,
            "can_column": _TEXT,
            "by_column": _TEXT,
            "rows": _each({"can": _TEXT, "by": _TEXT, "with": _each(_TEXT)}),
            "for_agents": _TEXT,
        },
        "read": {
            "lead": _TEXT,
            "says": _TEXT,
            "for_column": _TEXT,
            "read_column": _TEXT,
            "rows": _each({"for": _TEXT, "document": _TEXT}),
        },
    },
    "about": {
        "heading": _TEXT,
        "made_heading": _TEXT,
        "made": _each(_TEXT),
        "differences_lead": _TEXT,
        "difference": _TEXT,
        "machine": _TEXT,
        "changes_heading": _TEXT,
        "changes_columns": {
            "edition": _TEXT,
            "date": _TEXT,
            "written_for": _TEXT,
            "changes": _TEXT,
        },
    },
    "identity": {
        "describes": _TEXT,
        "packages": _TEXT,
        "packages_note": _TEXT,
        "specification": _TEXT,
        "snapshot": _TEXT,
        "edition": _TEXT,
        "edition_words": _TEXT,
        "changes_link": _TEXT,
        "contents": _TEXT,
    },
    "known_differences": _each({"kind": _TEXT, "line": _TEXT, "state": _TEXT, "why": _TEXT}),
    "editions": _each(
        {
            "edition": _NUMBER,
            "date": _TEXT,
            "written_for": _TEXT,
            "changes": _each(_TEXT),
            "facts": _keyed(_TEXT),
        }
    ),
    "sample": {"name": _TEXT, "says": _TEXT, "files": _keyed(_each(_WORDS))},
}

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _held(value: Any, shape: Any, where: str) -> None:
    """Refuse ``value`` unless it is exactly the shape ``shape`` describes."""
    if shape in (_TEXT, _WORDS):
        if not isinstance(value, str) or (shape == _TEXT and not value.strip()):
            wanted = "text" if shape == _WORDS else "text with something in it"
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} has to be {wanted}, and it is {value!r}."
            )
        if "\n" in value or "\r" in value:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} holds a line break. Every entry is "
                f"one line; a second paragraph is a second entry."
            )
        return
    if shape == _FLAG:
        if not isinstance(value, bool):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} has to be true or false, and it is "
                f"{value!r}."
            )
        return
    if shape == _NUMBER:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} has to be a whole number, and it is "
                f"{value!r}."
            )
        return
    if isinstance(shape, tuple):
        manner, inner = shape
        if manner == "maybe":
            if value is not None:
                _held(value, inner, where)
            return
        if manner == "each":
            if not isinstance(value, list):
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where} has to be a list."
                )
            for index, item in enumerate(value):
                _held(item, inner, f"{where}[{index}]")
            return
        if not isinstance(value, dict):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} has to be a set of named entries."
            )
        for key in sorted(value):
            _held(value[key], inner, f"{where}[{key!r}]")
        return
    if not isinstance(value, dict):
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} has to be a set of named entries."
        )
    missing = sorted(set(shape) - set(value))
    unknown = sorted(set(value) - set(shape))
    if missing or unknown:
        said = []
        if missing:
            said.append(f"is missing {', '.join(missing)}")
        if unknown:
            said.append(f"carries {', '.join(unknown)}, which nothing reads")
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} {' and '.join(said)}."
        )
    for key in sorted(shape):
        _held(value[key], shape[key], f"{where}.{key}" if where != "the file" else key)


def quick_reference_source(root: Path) -> dict[str, Any]:
    """The authored words, read from ``root`` and held to their schema.

    Raises:
        DocsQuickReferenceError: for a missing file, malformed JSON, another
            schema version, or any entry that is not the shape this module
            reads.
    """
    target = root.joinpath(*QUICK_REFERENCE_SOURCE.split("/"))
    if not target.is_file():
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE} is not there. The quick reference takes its "
            f"explanations and its sample project from that file, and without it the "
            f"page would be tables with nothing said about them."
        )
    try:
        source = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE} is not valid JSON: {error}"
        ) from error
    if not isinstance(source, dict):
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE} has to be a set of named entries."
        )
    if source.get("schema") != QUICK_REFERENCE_SOURCE_SCHEMA:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE} names the schema {source.get('schema')!r}; this "
            f"reader understands {QUICK_REFERENCE_SOURCE_SCHEMA!r}."
        )
    _held(source, _SHAPE, "the file")
    return source


def _prose(value: Any, where: str, skip: frozenset[str]) -> list[tuple[str, str]]:
    """Every authored sentence under ``value``, with where it was written."""
    if isinstance(value, str):
        return [(where, value)]
    if isinstance(value, list):
        found: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            found.extend(_prose(item, f"{where}[{index}]", skip))
        return found
    if isinstance(value, dict):
        found = []
        for key in sorted(value):
            if key in skip:
                continue
            found.extend(_prose(value[key], f"{where}.{key}" if where else key, skip))
        return found
    return []


def check_quick_reference_voice(source: Mapping[str, Any]) -> list[Finding]:
    """Every authored sentence of the quick reference is in the product's voice.

    ``DOC_VOICE_VIOLATION``. The whole authored file is prose a reader
    meets, so the whole file is governed — except the sample project,
    which is source text and not a sentence, and the ids that name what a
    row is about.
    """
    findings: list[Finding] = []
    skip = frozenset({"sample", "schema", "facts"})
    for where, written in _prose(dict(source), "", skip):
        for label, pattern in FORBIDDEN_IN_AUTHORED_PROSE:
            found = pattern.search(written)
            if found is None:
                continue
            findings.append(
                Finding(
                    code=DOC_VOICE_VIOLATION,
                    location=QUICK_REFERENCE_SOURCE,
                    message=(
                        f"{where} uses {found.group(0)!r}, which is {label} and not a "
                        f"word this product uses in text a reader sees"
                    ),
                    remediation=(
                        "write the plain-language term instead. The product says "
                        "feedback data, and it spells its own names with a digit zero."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# The sample project
# ---------------------------------------------------------------------------

_DECLARATION = re.compile(
    r"^(module|nerve|cell|ganglion|axon|helper|integration|test|doc-ref|doc-guide|example)"
    r"\s+(.+?)\s*$"
)


def sample_files(source: Mapping[str, Any]) -> dict[str, str]:
    """The sample project's files as text, keyed by their path inside it.

    What the suite writes into a temporary directory to build for real, and
    what this module cuts every sample from — one reading, so the project
    that is run and the project that is shown are the same bytes.
    """
    return {
        path: "\n".join(lines) + "\n" for path, lines in sorted(source["sample"]["files"].items())
    }


def _declarations(text: str) -> dict[str, tuple[str, str]]:
    """One file cut into its declarations: first-line key to (kind, text)."""
    blocks: dict[str, tuple[str, list[str]]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        matched = _DECLARATION.match(line)
        if matched:
            kind, rest = matched.groups()
            name = rest.split("::")[0].strip()
            current = []
            blocks[f"{kind} {name}"] = (kind, current)
        if current is not None:
            current.append(line)
    return {key: (kind, "\n".join(body).rstrip()) for key, (kind, body) in blocks.items()}


def _checked_sample(files: Mapping[str, str]) -> tuple[int, int]:
    """Refuse a sample project the strictest check reports anything about.

    Parsed and validated in process, one file at a time. Returns how many
    ``.s0ma`` files there are and how many tests the project's runner would
    collect, which the page states and the suite holds against a real run.
    """
    from s0ma_dsl.config import StrictnessMode
    from s0ma_dsl.errors import S0maError
    from s0ma_dsl.parser.s0ma_parser import parse_s0ma_with_warnings
    from s0ma_dsl.semantic.validator import validate_module

    modules = 0
    tests = 0
    for path, text in sorted(files.items()):
        if path.endswith(".py"):
            try:
                tree = ast.parse(text)
            except SyntaxError as error:
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: the sample file {path} is not valid "
                    f"Python: {error.msg} at line {error.lineno}."
                ) from error
            tests += sum(
                1
                for node in tree.body
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name.startswith("test")
            )
            continue
        if not path.endswith(".s0ma"):
            continue
        modules += 1
        # A name no file answers to, so nothing about the machine this
        # runs on can reach the check — and one whose last parts are the
        # sample's own, because the check reads them.
        named = f"{QUICK_REFERENCE_SOURCE}/{path}"
        reported: list[S0maError]
        try:
            module, warnings = parse_s0ma_with_warnings(
                text, named, mode=StrictnessMode.RELEASE
            )
            reported = [
                *warnings,
                *validate_module(module, mode=StrictnessMode.RELEASE, filename=named),
            ]
        except S0maError as error:
            reported = [error]
        if reported:
            first = reported[0]
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: the sample file {path} does not pass the "
                f"strictest check, so nothing cut from it may be shown. Line "
                f"{first.line}: {first.code}: {first.message} "
                f"({len(reported)} report(s) in all.)"
            )
        tests += sum(
            1 for key, (kind, _text) in _declarations(text).items() if kind == "test" and key
        )
    if not modules:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: the sample project holds no `.s0ma` file, so "
            f"every sample on the page would be empty."
        )
    return modules, tests


def _settings(
    source: Mapping[str, Any], files: Mapping[str, str], known: frozenset[str]
) -> list[str]:
    """The sample project's ``[tool.s0ma]`` table, as its author wrote it."""
    import tomllib

    name = source["shape"]["settings_file"]
    if name not in files:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: shape.settings_file names {name}, and the "
            f"sample project has no such file."
        )
    try:
        table = tomllib.loads(files[name]).get("tool", {}).get("s0ma", {})
    except tomllib.TOMLDecodeError as error:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: the sample file {name} is not valid TOML: {error}"
        ) from error
    if not table:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: the sample file {name} has no [tool.s0ma] "
            f"table, which is the one thing the page shows it for."
        )
    unknown = sorted(key for key in table if f"{CONFIG_CHANNEL}:{key}" not in known)
    if unknown:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: the sample project sets {', '.join(unknown)} "
            f"under [tool.s0ma], and s0ma reads no such setting."
        )
    lines = files[name].splitlines()
    start = lines.index("[tool.s0ma]")
    shown = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("["):
            break
        shown.append(line)
    while shown and not shown[-1].strip():
        shown.pop()
    return shown


# ---------------------------------------------------------------------------
# Resolving what the words name
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"<[^<>]+>")
_BACKTICKED = re.compile(r"`([^`]+)`")


def _command_line(write: str, interface: CommandInterface, where: str) -> None:
    """Refuse a command line the parser would not accept.

    Read against the argparse tree the command-line provider built: the
    command's own words, every option, every closed set a value is taken
    from, and how many plain values it takes.
    """
    try:
        tokens = shlex.split(write)
    except ValueError as error:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} writes {write!r}, which cannot be read "
            f"as a command line: {error}."
        ) from error
    expected = ["s0ma", *interface.path]
    if tokens[: len(expected)] != expected:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} names {interface.id} and writes "
            f"{write!r}; that command is typed `{' '.join(expected)}`."
        )
    options = {flag: option for option in interface.options for flag in option.flags}
    rest = tokens[len(expected) :]
    plain: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        if token.startswith("-") and len(token) > 1:
            option = options.get(token)
            if option is None:
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where} writes {write!r}, and "
                    f"`{' '.join(expected)}` has no option {token}. It has: "
                    f"{', '.join(sorted(options)) or 'none'}."
                )
            if option.takes_value:
                index += 1
                if index >= len(rest):
                    raise DocsQuickReferenceError(
                        f"{QUICK_REFERENCE_SOURCE}: {where} writes {write!r}, and "
                        f"{token} takes a value that is not there."
                    )
                _one_of(rest[index], option.choices, f"{where}: {token}")
        else:
            plain.append(token)
        index += 1
    required = sum(1 for argument in interface.arguments if argument.required)
    most = len(interface.arguments)
    unbounded = any(argument.nargs in {"*", "+"} for argument in interface.arguments)
    if len(plain) < required or (not unbounded and len(plain) > most):
        takes = str(required) if required == most else f"{required} to {most}"
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} writes {write!r}, which gives "
            f"{len(plain)} value(s); `{' '.join(expected)}` takes {takes}"
            f"{' or more' if unbounded else ''}."
        )
    for value, argument in zip(plain, interface.arguments, strict=False):
        _one_of(value, argument.choices, f"{where}: {argument.dest}")


def _one_of(value: str, choices: Sequence[str], where: str) -> None:
    if not choices or _PLACEHOLDER.fullmatch(value) or value in choices:
        return
    raise DocsQuickReferenceError(
        f"{QUICK_REFERENCE_SOURCE}: {where} is given {value!r}, and s0ma accepts "
        f"{', '.join(choices)}."
    )


def _options_said(says: str, interface: CommandInterface, where: str) -> None:
    """Every option an explanation mentions is one the command has."""
    options = {flag: option for option in interface.options for flag in option.flags}
    for span in _BACKTICKED.findall(says):
        words = span.split()
        for index, word in enumerate(words):
            if not word.startswith("--"):
                continue
            option = options.get(word)
            if option is None:
                # The explanation may be pointing at a sibling command;
                # a whole command line is checked where it is declared.
                if words[0] == "s0ma":
                    break
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where} mentions {word}, and "
                    f"{interface.public_name} has no such option."
                )
            if option.takes_value and index + 1 < len(words):
                _one_of(words[index + 1], option.choices, f"{where}: {word}")


class _Resolver:
    """What the composed model holds, indexed the way this module asks."""

    def __init__(
        self,
        bundle: DocsBundle,
        interfaces: Sequence[CommandInterface],
        *,
        docs_root: str,
        page: str,
    ) -> None:
        self.surfaces = {record.id: record for record in bundle.surfaces}
        self.documents = {record.id: record for record in bundle.documents}
        self.concepts = {record.id: record for record in bundle.concepts}
        self.interfaces = {item.id: item for item in interfaces}
        self.docs_root = docs_root
        self.page = page

    def surface(self, identifier: str, where: str, channels: Sequence[str] = ()) -> Any:
        found = self.surfaces.get(identifier)
        if found is None or (channels and found.channel not in channels):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} names {identifier}, and s0ma serves "
                f"nothing under that id. Either it was renamed or removed, and the page "
                f"has to follow it; or the id is misspelt."
            )
        return found

    def interface(self, identifier: str, where: str) -> CommandInterface:
        self.surface(identifier, where, (CLI_CHANNEL,))
        found = self.interfaces.get(identifier)
        if found is None:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} names {identifier}, and the command "
                f"line this build read does not hold it."
            )
        return found

    def document(self, identifier: str, where: str) -> dict[str, str]:
        found = self.documents.get(identifier)
        if found is None:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} names {identifier}, and the document "
                f"catalog has no such document."
            )
        return {"id": found.id, "title": found.title, "path": found.canonical_source}


# ---------------------------------------------------------------------------
# The composition: one value, from which both outputs are rendered
# ---------------------------------------------------------------------------


def _agreed(
    what: str, written: Sequence[str], accepted: Sequence[str], where: str, *, of: str
) -> None:
    """Refuse unless the words and the language name the same things.

    Both directions and duplicates, because each is a different mistake:
    something the language has and nobody described, something described
    that the language does not have, and something described twice.
    """
    repeated = sorted({item for item in written if list(written).count(item) > 1})
    if repeated:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} describes {', '.join(repeated)} more "
            f"than once."
        )
    missing = [item for item in accepted if item not in written]
    extra = [item for item in written if item not in accepted]
    if missing:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {of} {what} {', '.join(missing)}, and {where} "
            f"does not describe {'it' if len(missing) == 1 else 'them'}. Add an entry "
            f"for each, saying in plain words what it is for."
        )
    if extra:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: {where} describes {', '.join(extra)}, and {of} "
            f"no longer {what} {'it' if len(extra) == 1 else 'them'}. Remove "
            f"{'the entry' if len(extra) == 1 else 'those entries'}."
        )


def _kinds(
    source: Mapping[str, Any],
    facts: LanguageFacts,
    resolver: _Resolver,
    files: Mapping[str, str],
) -> list[dict[str, Any]]:
    types = {item["type"]: item for item in source["types"]}
    explained = {record.canonical_source for record in resolver.documents.values()}
    choice_of = {
        (kind, line): choice for choice in facts.choices for kind, line in choice.used_by
    }
    shown = {
        item["group"]: [value["value"] for value in item["values"] if not value["reserved"]]
        for item in source["choices"]
    }
    differences = {
        (item["kind"], item["line"], item["state"]) for item in source["known_differences"]
    }
    for kind, line, state in sorted(differences):
        fact = facts.kind(kind)
        held = next((item for item in fact.lines if item.name == line), None) if fact else None
        allowed = held is not None and (
            held.may_be_pending if state == "pending" else held.may_be_none
        )
        if state not in _STATES or not allowed:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: known_differences says the check refuses "
                f"`{state}` on {kind}.{line}, and the language's own table does not "
                f"allow it there in the first place. Remove the entry."
            )

    _agreed(
        "has the kind",
        [item["kind"] for item in source["kinds"]],
        [item.word for item in facts.kinds],
        "kinds",
        of="the language",
    )
    used: set[str] = set()
    composed: list[dict[str, Any]] = []
    for words in source["kinds"]:
        kind = words["kind"]
        where = f"kinds[{kind}]"
        fact = facts.kind(kind)
        assert fact is not None  # _agreed above
        concept = resolver.concepts.get(f"concept:{kind}")
        if concept is None:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: the language has the kind {kind} and no "
                f"concept:{kind} was composed, so the page cannot say what it is for."
            )
        if not words["first_line"].startswith(f"{kind} "):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where}.first_line is "
                f"{words['first_line']!r}, and the first line of {_a(kind)} opens with "
                f"the word {kind}."
            )
        _agreed(
            "accepts the line",
            [item["line"] for item in words["lines"]],
            [item.name for item in fact.lines],
            f"{where}.lines",
            of=_a(kind),
        )
        if (words["code"] is None) != (fact.code is None):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where}.code "
                + (
                    f"is empty, and {_a(kind)} has code after its `---` line."
                    if fact.code is not None
                    else f"describes code, and {_a(kind)} has none."
                )
            )
        by_name = {item.name: item for item in fact.lines}
        lines: list[dict[str, Any]] = []
        for entry in words["lines"]:
            held = by_name[entry["line"]]
            spot = f"{where}.lines[{entry['line']}]"
            for key in ("type", "also"):
                if entry[key] and entry[key] not in types:
                    raise DocsQuickReferenceError(
                        f"{QUICK_REFERENCE_SOURCE}: {spot}.{key} is {entry[key]!r}, and "
                        f"`types` explains no such word. It explains: "
                        f"{', '.join(sorted(types))}."
                    )
                used.add(entry[key])
            choice = choice_of.get((kind, held.name))
            if (entry["type"] == "choice") != (choice is not None):
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {spot} "
                    + (
                        "is written as a choice, and no closed set of words is read "
                        "for it from the language."
                        if choice is None
                        else f"takes one of a closed set of words ({choice.group}) and "
                        f"is not written as a choice."
                    )
                )
            may = []
            if held.may_be_none and (kind, held.name, "none") not in differences:
                may.append("none")
            if held.may_be_pending and (kind, held.name, "pending") not in differences:
                may.append("pending")
            values = list(shown[choice.group]) if choice else []
            lines.append(
                _kept(
                    line=held.name,
                    write=held.write,
                    may_be=may,
                    applies=held.applies,
                    type=entry["type"],
                    holds=_holds(entry, values, types),
                    choice=choice.group if choice else "",
                    values=values,
                    says=entry["says"],
                )
            )
        code = None
        if words["code"] is not None and fact.code is not None:
            if words["code"]["type"] not in types:
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where}.code.type is "
                    f"{words['code']['type']!r}, and `types` explains no such word."
                )
            used.add(words["code"]["type"])
            written = words["code"]["write"]
            openings = _CODE_OPENINGS[fact.code.write]
            if not written.startswith(openings):
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where}.code.write is {written!r}, and "
                    f"the language's own table has {_a(kind)}'s code as "
                    f"{fact.code.write}. It has to start with one of: "
                    f"{', '.join(openings)}."
                )
            code = _kept(
                write=fact.code.write,
                in_words=written,
                applies=fact.code.applies,
                type=words["code"]["type"],
                holds=types[words["code"]["type"]]["word"],
                says=words["code"]["says"],
            )
        if not words["samples"]:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where}.samples is empty, and every kind "
                f"on the page is shown in use."
            )
        samples = []
        for ref in words["samples"]:
            text = files.get(ref["file"])
            cut = _declarations(text).get(ref["declaration"]) if text is not None else None
            if cut is None or cut[0] != kind:
                raise DocsQuickReferenceError(
                    f"{QUICK_REFERENCE_SOURCE}: {where}.samples asks for "
                    f"{ref['declaration']!r} from {ref['file']}, and the sample project "
                    f"has no {kind} by that first line there."
                )
            samples.append(
                _kept(
                    caption=ref["caption"],
                    file=ref["file"],
                    declaration=ref["declaration"],
                    text=cut[1],
                )
            )
        page = f"{resolver.docs_root}/learn/{kind}.md"
        if page not in explained:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: the page would send a reader to {page} for "
                f"more about {_a(kind)}, and the document catalog has no such page."
            )
        composed.append(
            _kept(
                kind=kind,
                concept=concept.id,
                in_short=concept.summary,
                explained=page,
                when=words["when"],
                first_line=words["first_line"],
                opening=words["opening"],
                lines=lines,
                code=code,
                never_written=list(fact.worked_out),
                before_samples=list(words["before_samples"]),
                samples=samples,
                after_samples=list(words["after_samples"]),
            )
        )
    unused = sorted(set(types) - used)
    if unused:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: `types` explains {', '.join(unused)}, and no "
            f"line on the page holds one. Remove "
            f"{'the entry' if len(unused) == 1 else 'those entries'}."
        )
    return composed


def _choices(source: Mapping[str, Any], facts: LanguageFacts) -> list[dict[str, Any]]:
    _agreed(
        "has the set of words",
        [item["group"] for item in source["choices"]],
        [item.group for item in facts.choices],
        "choices",
        of="the language",
    )
    reach = dict(facts.reach)
    composed = []
    for words in source["choices"]:
        fact = facts.choice(words["group"])
        assert fact is not None  # _agreed above
        _agreed(
            "accepts",
            [item["value"] for item in words["values"]],
            list(fact.values),
            f"choices[{words['group']}].values",
            of=f"a line that takes a {words['title'].lower()}",
        )
        composed.append(
            {
                "choice": fact.group,
                "title": words["title"],
                "says": words["says"],
                "used_by": [f"{kind}.{line}" for kind, line in fact.used_by],
                "values": [
                    _kept(
                        value=item["value"],
                        says=item["says"],
                        looks_like=item["looks_like"],
                        kept_for_s0ma=item["reserved"] or "",
                        may_reach=list(reach[item["value"]]) if fact.group == "layer" else [],
                    )
                    for item in words["values"]
                ],
            }
        )
    return composed


def _commands(source: Mapping[str, Any], resolver: _Resolver) -> dict[str, Any]:
    first = []
    for index, entry in enumerate(source["commands"]["first_session"]):
        where = f"commands.first_session[{index}]"
        if entry["command"]:
            _command_line(entry["write"], resolver.interface(entry["command"], where), where)
        elif not entry["write"].startswith("cd "):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where} writes {entry['write']!r} and names "
                f"no command. The one line a session may hold that is not a s0ma "
                f"command is a change of folder."
            )
        first.append(_kept(**entry))
    groups = []
    for group in source["commands"]["groups"]:
        held = []
        for entry in group["commands"]:
            where = f"commands[{entry['write']}]"
            interface = resolver.interface(entry["command"], where)
            _command_line(entry["write"], interface, where)
            _options_said(entry["says"], interface, where)
            held.append(
                {"command": entry["command"], "write": entry["write"], "says": entry["says"]}
            )
        groups.append({"title": group["title"], "commands": held})
    return {"first_session": first, "groups": groups}


def _modes(
    source: Mapping[str, Any], bundle: DocsBundle, modes: Sequence[str]
) -> dict[str, Any]:
    _agreed(
        "has the mode",
        [item["mode"] for item in source["modes"]["values"]],
        list(modes),
        "modes.values",
        of="the check",
    )
    laddered = []
    codes = []
    unchanging = 0
    for record in sorted(bundle.surfaces, key=lambda item: item.id):
        if record.channel != DIAGNOSTIC_CHANNEL:
            continue
        held = fact_map(record.errors)
        if held.get(REGISTRY_KEY) == MATRIX_REGISTRY:
            laddered.append(held)
            codes.append(record.id)
        else:
            unchanging += 1
    if not laddered:
        raise DocsQuickReferenceError(
            "no report with a severity per mode was composed, so the page's table of "
            "modes would say every mode refuses nothing."
        )
    by_mode = {item["mode"]: item for item in source["modes"]["values"]}

    def only(mode: str) -> list[str]:
        """The reports this mode makes and no other mode does."""
        return [
            code
            for code, held in zip(codes, laddered, strict=True)
            if held.get(mode) != NOT_APPLICABLE
            and all(held.get(other) == NOT_APPLICABLE for other in modes if other != mode)
        ]

    return {
        "reports": len(laddered),
        "refused_in_every_mode": sum(
            1 for held in laddered if all(held.get(mode) == "error" for mode in modes)
        ),
        "unchanging": unchanging,
        "values": [
            _kept(
                mode=mode,
                meant_for=by_mode[mode]["meant_for"],
                treats=by_mode[mode]["treats"],
                refuses=sum(1 for held in laddered if held.get(mode) == "error"),
                warns=sum(1 for held in laddered if held.get(mode) == "warning"),
                skips=sum(1 for held in laddered if held.get(mode) == NOT_APPLICABLE),
                only_here=only(mode),
            )
            for mode in modes
        ],
    }


def _rules(source: Mapping[str, Any], resolver: _Resolver) -> list[dict[str, Any]]:
    composed = []
    for index, entry in enumerate(source["rules"]):
        reports = [
            resolver.surface(identifier, f"rules[{index}]", (DIAGNOSTIC_CHANNEL,)).id
            for identifier in entry["reports"]
        ]
        composed.append(_kept(rule=entry["rule"], detail=entry["detail"], reports=reports))
    return composed


def _more(source: Mapping[str, Any], resolver: _Resolver) -> dict[str, Any]:
    words = source["more"]
    for index, identifier in enumerate(words["ask_s0ma"]["commands"]):
        resolver.interface(identifier, f"more.ask_s0ma.commands[{index}]")
    rows = []
    for index, row in enumerate(words["ask_agent"]["rows"]):
        where = f"more.ask_agent.rows[{index}]"
        served = [resolver.surface(item, where) for item in row["with"]]
        try:
            by = row["by"].format(*(f"`{item.public_name}`" for item in served))
        except (IndexError, KeyError) as error:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: {where}.by has a place for something "
                f"`with` does not name ({error})."
            ) from error
        rows.append({"can": row["can"], "by": by, "with": [item.id for item in served]})
    return {
        "ask_s0ma": {
            "says": words["ask_s0ma"]["says"],
            "commands": list(words["ask_s0ma"]["commands"]),
        },
        "ask_agent": {
            "says": words["ask_agent"]["says"],
            "rows": rows,
            "for_agents": words["ask_agent"]["for_agents"],
        },
        "read": {
            "says": words["read"]["says"],
            "rows": [
                {
                    "for": row["for"],
                    **resolver.document(row["document"], f"more.read.rows[{index}]"),
                }
                for index, row in enumerate(words["read"]["rows"])
            ],
        },
    }


def _editions(
    source: Mapping[str, Any], pins: Mapping[str, str]
) -> list[dict[str, Any]]:
    editions = source["editions"]
    if not editions:
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: `editions` is empty, so the page could not say "
            f"when it was last revised."
        )
    for index, entry in enumerate(editions):
        if entry["edition"] != index + 1:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: editions[{index}] is numbered "
                f"{entry['edition']}. Editions are written oldest first and numbered "
                f"from 1, so this one is {index + 1}."
            )
        if not _DATE.fullmatch(entry["date"]):
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: editions[{index}].date is {entry['date']!r}; "
                f"a date is written year-month-day, as in 2026-09-29."
            )
        if not entry["changes"]:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: edition {entry['edition']} says nothing "
                f"changed. An edition exists because something did."
            )
    newest = editions[-1]
    if dict(newest["facts"]) != dict(pins):
        moved = sorted(
            group
            for group in set(pins) | set(newest["facts"])
            if pins.get(group) != newest["facts"].get(group)
        )
        raise DocsQuickReferenceError(
            f"{QUICK_REFERENCE_SOURCE}: what s0ma accepts has changed since edition "
            f"{newest['edition']} of the quick reference was written. What moved: "
            f"{', '.join(moved)}. The tables on the page follow by themselves; what is "
            f"owed is a line for the reader. Add an edition {newest['edition'] + 1} to "
            f"`editions` that says what changed, and give it these `facts`: "
            f"{json.dumps(dict(sorted(pins.items())), sort_keys=True)}"
        )
    return [
        {
            "edition": entry["edition"],
            "date": entry["date"],
            "written_for": entry["written_for"],
            "changes": list(entry["changes"]),
        }
        for entry in editions
    ]


def quick_reference(
    bundle: DocsBundle,
    *,
    source: Mapping[str, Any],
    facts: LanguageFacts,
    interfaces: Sequence[CommandInterface],
    modes: Sequence[str],
    packages: Sequence[tuple[str, str]],
    docs_root: str,
    page: str = QUICK_REFERENCE_OUTPUT,
    machine: str = QUICK_REFERENCE_MACHINE_OUTPUT,
) -> dict[str, Any]:
    """Everything the quick reference says, as one value.

    The machine output is this value written down, and the reader's page is
    this value rendered — so a fact is on both or on neither.

    Every argument is a reading the build already made, for the reason the
    other generated references take theirs: a renderer that re-read a
    source could describe one nobody composed.

    Raises:
        DocsQuickReferenceError: whenever the three readings disagree. See
            the module's own account of which disagreements there are.
    """
    resolver = _Resolver(bundle, interfaces, docs_root=docs_root, page=page)
    files = sample_files(source)
    modules, tests = _checked_sample(files)
    known = frozenset(resolver.surfaces)
    stamp = bundle.stamp
    return {
        "schema": QUICK_REFERENCE_SCHEMA,
        "title": source["page"]["title"],
        "summary": source["page"]["summary"],
        "identity": {
            "release": stamp.version_line(),
            "release_version": stamp.release_version,
            "build_channel": stamp.build_channel,
            "snapshot_hash": stamp.snapshot_hash,
            "packages": [
                {"distribution": name, "version": version} for name, version in sorted(packages)
            ],
            "specification": resolver.document(
                source["page"]["specification"], "page.specification"
            ),
            "edition": source["editions"][-1]["edition"] if source["editions"] else 0,
            "revised": source["editions"][-1]["date"] if source["editions"] else "",
            "documentation_root": docs_root,
            "readable": f"{docs_root}/{page}",
            "machine": f"{docs_root}/{machine}",
            "explanations": QUICK_REFERENCE_SOURCE,
            "read_from": list(facts.sources),
        },
        "orientation": {
            "paragraphs": list(source["orientation"]["paragraphs"]),
            "points": [dict(item) for item in source["orientation"]["points"]],
        },
        "file": {
            "sketch": list(source["shape"]["sketch"]),
            "notes": list(source["shape"]["notes"]),
            "project": list(source["shape"]["project"]),
            "settings": _settings(source, files, known),
            "indent": facts.indent,
        },
        "writing": {
            "write": [
                {"write": item["word"], "means": item["means"]}
                for item in _legend(source, "write", tuple(_WRITE_WORDS.values()))
            ],
            "may_be": [
                {"may_be": item["word"], "means": item["means"]}
                for item in _legend(source, "may", (*_STATES, _NEITHER))
                if item["word"] != _NEITHER
            ],
            "types": [dict(item) for item in source["types"]],
            "imports": source["reading"]["imports"],
            "long_forms": source["reading"]["long_forms"],
        },
        "choices": _choices(source, facts),
        "kinds": _kinds(source, facts, resolver, files),
        "commands": _commands(source, resolver),
        "modes": _modes(source, bundle, modes),
        "rules": _rules(source, resolver),
        "more": _more(source, resolver),
        "known_differences": [dict(item) for item in source["known_differences"]],
        "editions": _editions(source, fact_pins(facts, modes)),
        "sample": {
            "name": source["sample"]["name"],
            "says": source["sample"]["says"],
            "modules": modules,
            "tests": tests,
            "files": sorted(files),
            "kept_in": QUICK_REFERENCE_SOURCE,
        },
    }


def _a(word: str) -> str:
    """``word`` behind the article it takes: a nerve, an axon."""
    return f"{'an' if word[:1] in 'aeiou' else 'a'} {word}"


def _kept(**entries: Any) -> dict[str, Any]:
    """``entries`` without the ones that say nothing.

    An empty string or an empty list is a fact that is not there, and a
    program reading this document should not have to read past it. ``None``
    and ``False`` are answers and stay.
    """
    return {key: value for key, value in entries.items() if value not in ("", [], ())}


def _holds(
    entry: Mapping[str, Any], values: Sequence[str], types: Mapping[str, Mapping[str, str]]
) -> str:
    """What a line holds, in the words the legend explains."""
    word = types[entry["type"]]["word"]
    if values:
        word = f"{word} " + " ".join(f"`{value}`" for value in values)
    elif entry["of"]:
        word = f"{word} of {entry['of']}"
    if entry["also"]:
        word = f"{word}, or a {types[entry['also']]['word']}"
    return word


def _legend(
    source: Mapping[str, Any], which: str, wanted: Sequence[str]
) -> Sequence[Mapping[str, str]]:
    entries: Sequence[Mapping[str, str]] = source["reading"][which]
    _agreed(
        "uses the word",
        [item["word"] for item in entries],
        list(wanted),
        f"reading.{which}",
        of="the page",
    )
    return entries


# ---------------------------------------------------------------------------
# The two renderings
# ---------------------------------------------------------------------------


def render_machine(document: Mapping[str, Any]) -> str:
    """The quick reference as data: canonical JSON, one trailing line feed."""
    return canonical_json(document)


def _fenced(language: str, lines: Sequence[str]) -> list[str]:
    return [f"```{language}", *lines, "```"]


def _row(*cells: str) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(*headings: str) -> list[str]:
    return [_row(*headings), _row(*("---" for _ in headings))]


def _link_from(page: str) -> Callable[[str], str]:
    """How a repository-relative path is written as a link from ``page``."""
    here = page.split("/")[:-1]

    def link(relative: str) -> str:
        target, _, fragment = relative.partition("#")
        origin, there = list(here), target.split("/")
        while origin and there and origin[0] == there[0]:
            origin, there = origin[1:], there[1:]
        written = "/".join([".."] * len(origin) + there)
        return f"{written}#{fragment}" if fragment else written

    return link


def render_readable(document: Mapping[str, Any], words: Mapping[str, Any]) -> str:
    """The quick reference as a page.

    ``document`` is every fact on the page and ``words`` is the authored
    file it was composed from, which this rendering reads for one thing
    only: what to call things — headings, column titles, the labels of the
    legend. Nothing here decides a fact.
    """
    identity = document["identity"]
    docs_root = identity["documentation_root"]
    link = _link_from(identity["readable"])
    labels = words["identity"]
    shown_write = {item["word"]: item["shown_as"] for item in words["reading"]["write"]}
    shown_may = {item["word"]: item["shown_as"] for item in words["reading"]["may"]}
    means = {
        **{item["write"]: item["means"] for item in document["writing"]["write"]},
        **{item["may_be"]: item["means"] for item in document["writing"]["may_be"]},
    }

    headings = [
        words["orientation"]["heading"],
        words["shape"]["heading"],
        words["kinds_section"]["heading"],
        words["reading"]["heading"],
        words["choices_section"]["heading"],
        words["kinds_detail"]["heading"],
        words["commands_section"]["heading"],
        words["rules_section"]["heading"],
        words["more_section"]["heading"],
        words["about"]["heading"],
    ]
    claimed: dict[str, str] = {}
    for heading in (
        labels["contents"],
        *headings,
        words["about"]["made_heading"],
        words["about"]["changes_heading"],
        *(item["title"] for item in document["choices"]),
        *(item["kind"] for item in document["kinds"]),
    ):
        slug = anchor(heading)
        if slug in claimed:
            raise DocsQuickReferenceError(
                f"{QUICK_REFERENCE_SOURCE}: the headings {claimed[slug]!r} and "
                f"{heading!r} would both be reached at #{slug}, so every link to the "
                f"second would land on the first. One of them has to change."
            )
        claimed[slug] = heading

    packages = identity["packages"]
    named = ", ".join(f"`{item['distribution']}`" for item in packages)
    if {item["version"] for item in packages} == {identity["release_version"]}:
        packages_cell = f"{named}, {labels['packages_note']}"
    else:
        packages_cell = ", ".join(
            f"`{item['distribution']}` {item['version']}" for item in packages
        )
    specification = identity["specification"]

    lines: list[str] = [
        f"# {document['title']}",
        "",
        GENERATED_NOTE,
        "",
        document["summary"],
        "",
        *_table("", ""),
        _row(f"**{labels['describes']}**", f"s0ma {identity['release']}"),
        _row(f"**{labels['packages']}**", packages_cell),
        _row(
            f"**{labels['specification']}**",
            f"[{cell(specification['title'])}]({link(specification['path'])})",
        ),
        _row(f"**{labels['snapshot']}**", f"`{identity['snapshot_hash']}`"),
        _row(
            f"**{labels['edition']}**",
            labels["edition_words"].format(
                edition=identity["edition"], date=identity["revised"]
            )
            + f" — [{labels['changes_link']}](#{anchor(words['about']['changes_heading'])})",
        ),
        "",
    ]
    if identity["build_channel"] != "release":
        lines.extend([words["page"]["preview_note"], ""])

    lines.extend([f"## {labels['contents']}", ""])
    lines.extend(
        f"{index}. [{heading}](#{anchor(heading)})"
        for index, heading in enumerate(headings, start=1)
    )
    lines.append("")

    # -- orientation --------------------------------------------------------
    lines.extend([f"## {words['orientation']['heading']}", ""])
    for paragraph in document["orientation"]["paragraphs"]:
        lines.extend([paragraph, ""])
    lines.extend([words["orientation"]["lead"], ""])
    lines.extend(
        f"{index}. **{item['say']}** {item['because']}"
        for index, item in enumerate(document["orientation"]["points"], start=1)
    )
    lines.append("")

    # -- the shape of a file ------------------------------------------------
    lines.extend([f"## {words['shape']['heading']}", ""])
    lines.extend(_fenced("text", document["file"]["sketch"]))
    lines.append("")
    lines.extend(f"- {note}" for note in document["file"]["notes"])
    lines.extend(["", words["shape"]["project_lead"], ""])
    lines.extend(_fenced("text", document["file"]["project"]))
    lines.extend(["", words["shape"]["settings_lead"], ""])
    lines.extend(_fenced("toml", document["file"]["settings"]))
    lines.append("")

    # -- the kinds ----------------------------------------------------------
    section = words["kinds_section"]
    titles = section["columns"]
    lines.extend(
        [
            f"## {section['heading']}",
            "",
            section["lead"].format(count=len(document["kinds"])),
            "",
            *_table(titles["kind"], titles["when"], titles["in_short"], titles["code"]),
        ]
    )
    for kind in document["kinds"]:
        code = kind["code"]
        if code is None:
            has = "none"
        elif code["type"] == "prose":
            has = "writing"
        elif code["in_words"].startswith("Always"):
            has = "always"
        elif code["in_words"].startswith("Optional"):
            has = "optional"
        else:
            has = "usually"
        lines.append(
            _row(
                f"[`{kind['kind']}`](#{anchor(kind['kind'])})",
                cell(kind["when"]),
                f"{cell(kind['in_short'])} [{section['more']}]({link(kind['explained'])})",
                section["code"][has],
            )
        )
    lines.extend(["", section["choosing"], ""])

    # -- how to read --------------------------------------------------------
    reading = words["reading"]
    columns = words["kinds_detail"]["columns"]
    lines.extend([f"## {reading['heading']}", "", reading["lead"], ""])
    lines.extend(
        [reading["write_lead"], "", *_table(columns["write"], reading["means_column"])]
    )
    lines.extend(
        _row(item["shown_as"], cell(means[item["word"]])) for item in reading["write"]
    )
    lines.extend(
        ["", reading["may_lead"], "", *_table(columns["may"], reading["means_column"])]
    )
    lines.extend(
        _row(item["shown_as"], cell(means.get(item["word"], item["means"])))
        for item in reading["may"]
    )
    lines.extend(
        [
            "",
            reading["holds_lead"],
            "",
            *_table(columns["holds"], reading["looks_like_column"]),
        ]
    )
    lines.extend(
        _row(item["word"], cell(item["looks_like"])) for item in document["writing"]["types"]
    )
    lines.extend(["", document["writing"]["imports"], "", document["writing"]["long_forms"], ""])

    # -- the words you choose from -----------------------------------------
    section = words["choices_section"]
    titled = {item["group"]: item for item in words["choices"]}
    lines.extend([f"## {section['heading']}", ""])
    for group in document["choices"]:
        held = titled[group["choice"]]
        lines.extend([f"### {group['title']}", "", _sentence(group["says"]), ""])
        titles = [group["title"], held["column"]]
        if held["looks_like_column"]:
            titles.append(held["looks_like_column"])
        reaches = any("may_reach" in value for value in group["values"])
        if reaches:
            titles.append(section["reach_column"])
        lines.extend(_table(*titles))
        kept = []
        for value in group["values"]:
            if value.get("kept_for_s0ma") and not reaches:
                kept.append(value)
                continue
            cells = [f"`{value['value']}`", cell(value["says"])]
            if held["looks_like_column"]:
                cells.append(cell(value.get("looks_like", "")))
            if reaches:
                cells.append(" ".join(f"`{item}`" for item in value["may_reach"]))
            lines.append(_row(*cells))
        lines.append("")
        for value in kept:
            lines.extend(
                [section["reserved"].format(value=f"`{value['value']}`", says=value["says"]), ""]
            )

    # -- each declaration ---------------------------------------------------
    detail = words["kinds_detail"]
    lines.extend([f"## {detail['heading']}", "", detail["lead"], ""])
    for kind in document["kinds"]:
        lines.extend([f"### {kind['kind']}", "", kind["opening"], ""])
        lines.extend(
            _table(
                columns["line"], columns["write"], columns["may"], columns["holds"], columns["says"]
            )
        )
        for line in kind["lines"]:
            may = " · ".join(shown_may[item] for item in line.get("may_be", ()))
            lines.append(
                _row(
                    f"`{line['line']}`",
                    shown_write[line["write"]],
                    may or shown_may[_NEITHER],
                    cell(line["holds"]),
                    cell(line["says"]),
                )
            )
        code = kind["code"]
        if code is not None:
            lines.append(
                _row(
                    detail["prose_row"] if code["type"] == "prose" else detail["code_row"],
                    cell(code["in_words"]),
                    shown_may[_NEITHER],
                    cell(code["holds"]),
                    cell(code["says"]),
                )
            )
        lines.append("")
        for paragraph in kind.get("before_samples", ()):
            lines.extend([paragraph, ""])
        for sample in kind["samples"]:
            if sample.get("caption"):
                lines.extend([sample["caption"], ""])
            lines.extend(_fenced("s0ma", sample["text"].split("\n")))
            lines.append("")
        for paragraph in kind.get("after_samples", ()):
            lines.extend([paragraph, ""])

    # -- commands -----------------------------------------------------------
    commands = document["commands"]
    section = words["commands_section"]
    lines.extend([f"## {section['heading']}", "", words["commands"]["lead"], ""])
    width = max(len(item["write"]) for item in commands["first_session"])
    lines.extend(
        _fenced(
            "bash",
            [
                f"{item['write'].ljust(width)}   # {item['note']}"
                if item.get("note")
                else item["write"]
                for item in commands["first_session"]
            ],
        )
    )
    lines.append("")
    for group in commands["groups"]:
        lines.extend(
            [
                f"**{group['title']}**",
                "",
                *_table(section["command_column"], section["does_column"]),
            ]
        )
        lines.extend(
            _row(
                f"[`{cell(item['write'])}`]"
                f"({link(deep_link(item['command'], docs_root=docs_root))})",
                cell(item["says"]),
            )
            for item in group["commands"]
        )
        lines.append("")
    modes = document["modes"]
    titles = words["modes_columns"]
    lines.extend(
        [
            words["modes"]["lead"],
            "",
            *_table(
                titles["mode"],
                titles["meant_for"],
                titles["treats"],
                titles["refuses"],
                titles["warns"],
                titles["skips"],
            ),
        ]
    )
    lines.extend(
        _row(
            f"`{item['mode']}`",
            cell(item["meant_for"]),
            cell(item["treats"]),
            str(item["refuses"]),
            str(item["warns"]),
            str(item["skips"]),
        )
        for item in modes["values"]
    )
    lines.extend(
        [
            "",
            words["modes"]["unchanging"].format(
                reports=modes["reports"],
                always=modes["refused_in_every_mode"],
                unchanging=modes["unchanging"],
            ),
            "",
        ]
    )
    for item in modes["values"]:
        if item.get("only_here"):
            lines.extend(
                [
                    words["modes"]["only_here"].format(
                        mode=f"`{item['mode']}`",
                        reports=", ".join(
                            f"[`{code.partition(':')[2]}`]"
                            f"({link(deep_link(code, docs_root=docs_root))})"
                            for code in item["only_here"]
                        ),
                    ),
                    "",
                ]
            )

    # -- rules --------------------------------------------------------------
    section = words["rules_section"]
    lines.extend([f"## {section['heading']}", ""])
    for index, rule in enumerate(document["rules"], start=1):
        said = f"{index}. **{rule['rule']}** {rule['detail']}"
        if rule.get("reports"):
            said += (
                f" {section['reported_as']} "
                + ", ".join(
                    f"[`{item.partition(':')[2]}`]({link(deep_link(item, docs_root=docs_root))})"
                    for item in rule["reports"]
                )
                + "."
            )
        lines.append(said)
    lines.append("")

    # -- finding out more ---------------------------------------------------
    more = document["more"]
    titles = words["more"]
    lines.extend(
        [
            f"## {words['more_section']['heading']}",
            "",
            f"**{titles['ask_s0ma']['lead']}** {more['ask_s0ma']['says']}",
            "",
            f"**{titles['ask_agent']['lead']}** {more['ask_agent']['says']}",
            "",
            *_table(titles["ask_agent"]["can_column"], titles["ask_agent"]["by_column"]),
        ]
    )
    lines.extend(_row(cell(row["can"]), cell(row["by"])) for row in more["ask_agent"]["rows"])
    lines.extend(
        [
            "",
            more["ask_agent"]["for_agents"],
            "",
            f"**{titles['read']['lead']}** {more['read']['says']}",
            "",
            *_table(titles["read"]["for_column"], titles["read"]["read_column"]),
        ]
    )
    lines.extend(
        _row(cell(row["for"]), f"[{cell(row['title'])}]({link(row['path'])})")
        for row in more["read"]["rows"]
    )
    lines.append("")

    # -- about --------------------------------------------------------------
    about = words["about"]
    sample = document["sample"]
    lines.extend([f"## {about['heading']}", "", f"### {about['made_heading']}", ""])
    lines.extend(
        "- " + item.format(modules=sample["modules"], tests=sample["tests"])
        for item in about["made"]
    )
    lines.append("")
    differences = document.get("known_differences", ())
    if differences:
        lines.extend([about["differences_lead"].format(count=len(differences)), ""])
        lines.extend(
            "- "
            + about["difference"].format(
                line=f"`{item['line']}`",
                kind=f"`{item['kind']}`",
                state=shown_may[item["state"]],
            )
            + f" {item['why']}"
            for item in differences
        )
        lines.append("")
    lines.extend(
        [
            about["machine"].format(path=identity["machine"]),
            "",
            f"### {about['changes_heading']}",
            "",
            *_table(
                about["changes_columns"]["edition"],
                about["changes_columns"]["date"],
                about["changes_columns"]["written_for"],
                about["changes_columns"]["changes"],
            ),
        ]
    )
    lines.extend(
        _row(
            str(entry["edition"]),
            entry["date"],
            f"s0ma {entry['written_for']}",
            cell(" ".join(entry["changes"])),
        )
        for entry in reversed(document["editions"])
    )
    return "\n".join(lines) + "\n"


def _sentence(text: str) -> str:
    """``text`` opening with a capital, as a sentence standing by itself."""
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------
# What the application calls
# ---------------------------------------------------------------------------


def compose(
    bundle: DocsBundle,
    words: Mapping[str, Any] | DocsModelError,
    *,
    interfaces: Sequence[CommandInterface],
    modes: Sequence[str],
    packages: Sequence[tuple[str, str]],
    docs_root: str,
) -> tuple[Callable[[], str], Callable[[], str]]:
    """The two renderings, ready to be asked for.

    Composed once, here, so the page and the data are two renderings of one
    value. ``words`` is the authored file as the application read it, or
    the refusal that reading ended in. Either that refusal or one raised
    while composing is kept and raised again by each rendering, which puts
    the reason on both outputs that were not written — the shape the
    coverage report and the self-description already share one measurement
    in.
    """
    try:
        if isinstance(words, DocsModelError):
            raise words
        document = quick_reference(
            bundle,
            source=words,
            facts=language_facts(),
            interfaces=interfaces,
            modes=modes,
            packages=packages,
            docs_root=docs_root,
        )
        page = render_readable(document, words)
        data = render_machine(document)
    except DocsModelError as error:
        refused = error

        def refuse() -> str:
            raise refused

        return refuse, refuse
    return (lambda: page), (lambda: data)
