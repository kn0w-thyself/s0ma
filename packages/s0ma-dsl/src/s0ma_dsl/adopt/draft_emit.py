"""Draft emitter — turn a harvested draft model into ``.s0ma`` text.

This is the second half of the mechanical step of rung 3. D1's harvester
reads a plain-Python file and returns a
:class:`~s0ma_dsl.adopt.model.DraftModule`: what the file *is*, never
what it *means*. :func:`emit_draft` turns that record into the text of a
``.s0ma`` file — one the real parser accepts today — with every piece of
meaning the file did not already carry written as an unmistakable
``FIXME(adopt):`` placeholder that ``s0ma check`` will refuse (ruling
D-3 and R-5, and the ``ADOPT_PLACEHOLDER_INTENT`` diagnostic D3 adds).

Nothing here guesses an intent, and nothing here reformats code.

Public surface
--------------

``emit_draft(draft, *, proposed_layer, layer_candidates)``
    The one entry point. Pure: the same draft always gives byte-identical
    text. LF line endings, one trailing newline, no timestamps, no
    absolute paths.

``PLACEHOLDERS``
    The placeholder sentence for every authored-meaning field, keyed by
    ``(form, field)``. Read it rather than re-typing a sentence: the
    tests, D3's diagnostics and the guide all quote from one place.

``DRAFT_VERSION`` / ``FALLBACK_LAYER`` / ``PROVENANCE_PREFIX``
    The three constants a reader of a draft sees at the top of the file.


What the emitter derives, and what it refuses to
------------------------------------------------

**Derived — structure, which the file already states.** The declaration
form (``nerve`` / ``helper`` / ``cell``) and the cell kind come from the
harvester. ``visibility:`` is ``PUBLIC`` for a name the module exports
and ``INTERNAL`` for every other, which is the Python underscore/
``__all__`` convention read back, not a judgement. A nerve's ``kind:``
is ``FUNCTION`` and its ``evaluates_at:`` is ``FUNCTION_BOUNDARY``
because the body *is* a plain function; a nerve whose real archetype is
a service or an adapter is the author's call to make, and the intent
placeholder says so.

**Refused — meaning, which only a person holds.** ``intent``,
``expects``, ``guarantees``, ``forbids`` and ``schema`` are emitted as
``FIXME(adopt):`` sentences telling whoever finishes the draft what to
write, in plain words. Where a real authored value was lifted from an
existing ``@component`` registration, that value is emitted instead and
is never replaced by a placeholder.

The Python module's docstring is **never** promoted to the module
intent. Prose about a file is not a declared intent, and promoting it
would put un-reviewed words where ``s0ma check`` is meant to refuse
until someone has written them. The docstring's first line rides
*inside* the placeholder instead, as a suggestion the author may accept
in one keystroke or overwrite.


The three shapes this emitter has to get exactly right
------------------------------------------------------

**1. A header must author all six requires-family fields.** The spec
prose calls ``soft_requires`` / ``runtime_only_requires`` /
``deferred_requires`` / ``exports_helpers`` optional; the M3A semantic
-state contract made all six semantic-required-with-``none``
(``semantic_state.py``), so a header that omits one raises
``SEMANTIC_REQUIRED_STATE_OMITTED`` at parse time — error in every mode,
and the message points at the module rather than at the draft that
wrote it. Friction entry F-D1-4. Every header this emitter writes
authors all six, ``none`` included.

**2. A body is emitted verbatim, indented by exactly one body indent.**
Every line of the harvested body gets four leading spaces; a line that
is empty stays empty. The parser's own dedent
(``body_extractor._dedent_body``) takes exactly those four spaces back,
so the text the compiler sees is the text the author wrote — comments,
blank lines, odd spacing, trailing whitespace and all. The uniform
indent is also what makes the body *safe*: the declaration splitter ends
a body only at a line that is unindented **and** matches a declaration
header, so an indented body line reading ``---``, ``module fake`` or
``nerve g :: DOMAIN`` — all of which occur inside real docstrings — is
carried through untouched instead of cutting the declaration short.
The one thing that does not survive is a run of blank lines at the very
end of a body: the splitter strips those before the body is stored.

**3. A quoted string has no escape for a double quote.** The grammar's
``QUOTED_STRING`` runs to the next ``"``, so a ``"`` inside a field
value would end the value early. Every quoted value this emitter writes
passes through :func:`_quote`, which turns a double quote into a single
quote and collapses any run of whitespace (a newline included) into one
space, because a field value is one line. Those two substitutions are
the only changes ever made to a lifted authored value; the carried
*code* is never touched.


Layers
------

A module sits at exactly one layer and every declaration in it shares
that layer (``LAYER_MISMATCH``, error in every mode). The layer used is,
in order: the ``proposed_layer`` argument (B3's proposal when its
confidence is high, or the user's ``--layer``); the layer on the draft;
the one layer every lifted registration agreed on; and finally
:data:`FALLBACK_LAYER`. When it comes from that last fallback the module
intent placeholder says so in plain words and names the candidates, so
the choice is visible where the compiler already refuses, rather than
hidden in a comment the parser cannot see.


Un-placeable source
-------------------

Text the harvester could not place rides in the carrier D1 decided on
and proved: one ``cell`` of ``kind: CONSTANT`` and
``visibility: INTERNAL``, named ``ADOPT_UNPLACED_<start>_<end>``, whose
``schema:`` opens with ``adopt: unplaced`` and whose body assigns that
name a string literal holding the source verbatim. The emitter does not
re-derive any of that: it calls :func:`~s0ma_dsl.adopt.harvest.
unplaced_cell_name`, :func:`~s0ma_dsl.adopt.harvest.unplaced_cell_schema`
and :func:`~s0ma_dsl.adopt.harvest.render_unplaced_value` so the
emitter, the harvester and D3's checker read the same rules from one
place. Carriers are interleaved with the declarations in source order,
so the draft reads like the file it came from.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.harvest import (
    UNPLACED_CELL_KIND,
    UNPLACED_CELL_VISIBILITY,
    render_unplaced_value,
    unplaced_cell_name,
    unplaced_cell_schema,
)
from s0ma_dsl.adopt.model import DRAFT_INTENT_MARKER

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from s0ma_dsl.adopt.model import DraftDeclaration, DraftModule, DraftUnplaced

__all__ = [
    "DRAFT_VERSION",
    "FALLBACK_LAYER",
    "INLINE_LIST_MAX",
    "PLACEHOLDERS",
    "PROVENANCE_PREFIX",
    "UNPLACED_CELL_INTENT",
    "emit_draft",
]


# ---------------------------------------------------------------------------
# The constants a reader of a draft meets first
# ---------------------------------------------------------------------------

PROVENANCE_PREFIX = "# adopt_source: "
"""Opening comment of every draft: which bytes this draft came from.

``# adopt_source: <project-relative POSIX path>@sha256:<hex>``. A
comment, not a ``metadata:`` entry, because a module's ``metadata:``
parses but is silently dropped by the module builder (friction F-D1-1),
so it could not carry provenance to anything that reads it. The
machine-checkable link is the baseline record; this line is for the
people and the tools that read the source.
"""

DRAFT_VERSION = "0.1.0"
"""``version:`` every draft opens at. A draft is a work in progress."""

FALLBACK_LAYER = "DOMAIN"
"""The layer a draft takes when nothing said which layer this module is.

Not a guess dressed up as an answer: whenever this value is used, the
module's intent placeholder says the draft could not tell and names the
candidates. ``DOMAIN`` matches what ``s0ma new module`` defaults to.
"""

INLINE_LIST_MAX = 4
"""Longest list still written inline; longer ones take the block form.

Both forms are exactly equivalent to the parser (spec §4.5.4). The
threshold is about a person reading the draft: a sixteen-entry
``requires:`` on one line is unreadable, and these lists are meant to be
edited by hand.
"""

UNPLACED_CELL_INTENT = (
    "Source the retrofit could not place. Move it into a declaration, then delete this."
)
"""``intent:`` of every un-placeable-source carrier cell.

Deliberately *not* a ``FIXME(adopt):`` placeholder: it is a real
instruction, and the debt it carries has its own marker
(``adopt: unplaced``) and its own diagnostic (``ADOPT_UNPLACED_CODE``).
Keeping the two markers apart keeps the count of ``FIXME(adopt):``
markers an honest measure of un-written *meaning*.
"""


# ---------------------------------------------------------------------------
# The placeholders — every sentence in one place
# ---------------------------------------------------------------------------

PLACEHOLDERS: dict[tuple[str, str], str] = {
    ("module", "intent"): (
        "say in one sentence what this module is responsible for, and what it leaves "
        "to other modules"
    ),
    ("nerve", "intent"): "say in one sentence what this function is for and who calls it",
    ("nerve", "expects"): (
        "say what has to be true before this is called: what each argument must hold, "
        "and anything that must already have happened"
    ),
    ("nerve", "guarantees"): (
        "say what the caller gets back when this works, and name anything it refuses "
        "to do or raises an error about"
    ),
    ("nerve", "forbids"): (
        "say what this must never do, however it is called; write none if there is "
        "nothing to rule out"
    ),
    ("cell", "intent"): "say in one sentence why this exists and who reads it",
    ("cell", "schema"): "say what this holds and what shape it has, in plain words",
    ("helper", "intent"): (
        "say in one sentence why this module-private helper exists and which "
        "declaration in this module uses it"
    ),
}
"""The instruction written into each un-authored field, by form and field.

One home for every sentence, so the emitter, its tests, D3's diagnostics
and the guide cannot drift apart. Each is written for an intelligent
non-programmer and says what to write, not what is missing. The
:data:`~s0ma_dsl.adopt.model.DRAFT_INTENT_MARKER` prefix and the closing
full stop are added by :func:`placeholder`.
"""

_DOCSTRING_HINT = (
    "The Python file's docstring began: '{first_line}' — use that if it is true, "
    "rewrite it if it is not."
)
"""Suggestion appended to the module intent placeholder when there was a docstring."""

_STRING_RULE_NOTE = (
    "Writing a field: the value goes in double quotes on one line, and everything "
    "between them is taken exactly as written — there are no escapes, so quote "
    "anything inside the sentence with 'single quotes' rather than a backslash."
)
"""The one rule somebody needs before writing the first placeholder.

G1's H-5: the trial's agent typed an escaped double quote inside a
value, realised nothing had told it whether escapes are honoured, and
changed its mind on the strength of what the placeholder text itself
did. The rule is read off the parser — :func:`_quote` here and
``_parse_string_field`` there both take the outer quotes off and keep
the rest verbatim — so a backslash survives into the built module as a
backslash.
"""

#: Which way the layer rule points, in one clause (G1's H-4). Read off
#: the reachability matrix the resolver enforces
#: (``_ALLOWED_TARGET_LAYERS`` in ``resolver/dependency.py``, which fires
#: ``CROSS_LAYER_DEPENDENCY``): a module may use its own layer and the
#: ones below it, never the ones above. Saying so turns "choose a layer"
#: from a guess into something a person can work out from the imports
#: they already have.
_LAYER_RULE = (
    "The rule that settles it: a module may only use modules at its own layer or "
    "below — DOMAIN may use DOMAIN and FRAMEWORK only, APPLICATION may also use "
    "DOMAIN, and PRESENTATION and INFRASTRUCTURE may use DOMAIN and APPLICATION — "
    "so the answer is the layer that lets this module import what it already imports"
)

_LAYER_HINT_WITH_CANDIDATES = (
    "Also choose this module's layer: the draft wrote {fallback} because nothing in "
    "the file said which layer this is, and the candidates are {candidates}. A module "
    f"sits at exactly one layer and every declaration in it shares that layer. "
    f"{_LAYER_RULE}."
)

_LAYER_HINT_BARE = (
    "Also choose this module's layer: the draft wrote {fallback} because nothing in "
    "the file said which layer this is, and the four layers are {candidates}. A module "
    f"sits at exactly one layer and every declaration in it shares that layer. "
    f"{_LAYER_RULE}."
)

_KIND_OVERRIDE_HINT = (
    "The draft wrote kind: {used} here because a cell of kind {hinted} may not hold "
    "{shape}, and this body is {shape}. Change the kind once you have decided what "
    "this really is."
)

_ALL_LAYERS = ("DOMAIN", "APPLICATION", "INFRASTRUCTURE", "PRESENTATION")


def placeholder(form: str, field: str, *extra: str) -> str:
    """The full placeholder text for one field, marker and all.

    ``FIXME(adopt): <instruction>.`` followed by any *extra* sentences,
    each already punctuated. Every un-authored field in a draft goes
    through here, so ``s0ma check`` has exactly one string shape to
    match and a reader has exactly one thing to look for.
    """
    sentences = [f"{DRAFT_INTENT_MARKER} {PLACEHOLDERS[form, field]}.", *extra]
    return " ".join(sentence for sentence in sentences if sentence)


# ---------------------------------------------------------------------------
# Field tables — the order a declaration's fields are written in
# ---------------------------------------------------------------------------

_MODULE_FIELD_ORDER = (
    "layer",
    "version",
    "intent",
    "exports",
    "requires",
    "uses",
    "soft_requires",
    "runtime_only_requires",
    "deferred_requires",
    "exports_helpers",
)

_NERVE_FIELD_ORDER = (
    "kind",
    "visibility",
    "intent",
    "expects",
    "guarantees",
    "forbids",
    "evaluates_at",
    "provides",
    "returns",
    "raises",
    "interface",
    "latency_ms",
    "depends_on",
    "internal",
    "expected_exceptions",
    "consumes_via_dict",
    "declares_attributes",
    "covered_by",
)

_CELL_FIELD_ORDER = ("kind", "visibility", "intent", "schema", "invariants", "covered_by")

_HELPER_FIELD_ORDER = ("intent",)

_FIELD_ORDER: dict[str, tuple[str, ...]] = {
    "module": _MODULE_FIELD_ORDER,
    "nerve": _NERVE_FIELD_ORDER,
    "cell": _CELL_FIELD_ORDER,
    "helper": _HELPER_FIELD_ORDER,
}

_QUOTED_FIELDS = frozenset({"intent", "expects", "guarantees", "forbids", "schema", "invariants"})
"""Fields whose value is prose and is written inside double quotes."""

_BODY_INDENT = "    "
_FIELD_INDENT = "    "


# ---------------------------------------------------------------------------
# Cell kinds and the body shapes they are allowed to hold
# ---------------------------------------------------------------------------

_CLASS_KINDS = frozenset({"MODEL", "EXCEPTION", "ENUM", "CONFIG"})
"""Cell kinds whose body must be a class definition (``body_extractor``)."""

_VALUE_KINDS = frozenset({"CONSTANT", "TYPE"})
"""Cell kinds whose body must be an assignment or a type alias."""

_SHAPE_WORDS = {"class": "a class", "value": "a plain value"}


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def emit_draft(
    draft: DraftModule,
    *,
    proposed_layer: str | None = None,
    layer_candidates: Sequence[str] = (),
) -> str:
    """Render *draft* as the text of a ``.s0ma`` file.

    Pure and deterministic: the same draft always produces the same
    bytes, on every platform. The text uses LF line endings and ends
    with exactly one newline; it carries no timestamp, no absolute path
    and nothing that depends on dictionary or set ordering.

    Args:
        draft: The harvested module, from
            :func:`~s0ma_dsl.adopt.harvest.harvest_module`.
        proposed_layer: The layer to write when the draft carries none —
            B3's proposal when its confidence is high, or a ``--layer``
            the user typed. Passing it is how the caller avoids the
            fallback layer and its placeholder sentence; the emitter
            never goes looking for a proposal itself.
        layer_candidates: The layers a proposal thought plausible. Named
            in the placeholder when the fallback layer had to be used,
            so whoever finishes the draft sees the shortlist rather than
            the whole vocabulary.

    Returns:
        The complete ``.s0ma`` source. It parses; it does not *check* —
        every un-authored field carries a ``FIXME(adopt):`` placeholder
        that ``s0ma check`` refuses, on purpose (ruling R-5).
    """
    module_layer, layer_is_fallback = _module_layer(draft, proposed_layer)
    lines: list[str] = []

    lines.append(f"{PROVENANCE_PREFIX}{draft.source_path}@{draft.source_hash}")
    lines.extend(_note_comments([_STRING_RULE_NOTE, *draft.notes]))
    lines.extend(
        _module_header(
            draft,
            layer=module_layer,
            layer_is_fallback=layer_is_fallback,
            layer_candidates=layer_candidates,
        )
    )

    for block in _blocks_in_source_order(draft):
        lines.append("")
        if isinstance(block, tuple):
            lines.extend(_declaration_lines(block[1], layer=module_layer, draft=draft))
        else:
            lines.extend(_carrier_lines(block, layer=module_layer, draft=draft))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The module header
# ---------------------------------------------------------------------------


def _module_header(
    draft: DraftModule,
    *,
    layer: str,
    layer_is_fallback: bool,
    layer_candidates: Sequence[str],
) -> list[str]:
    """The ``module`` declaration: one name line and its ten fields.

    ``soft_requires``, ``runtime_only_requires`` and ``exports_helpers``
    are always ``none``. Nothing in a plain Python file says an import is
    optional or that it is there only for a runtime the checker cannot
    see — those are authored choices, and a draft that guessed at one
    would be putting words in somebody's mouth. ``exports_helpers`` is
    ``none`` because the harvester has already ruled that a helper named
    in ``__all__`` stays out of the public surface, and says so in a note
    telling the author to promote it to a nerve if it really belongs
    there; writing the name into ``exports_helpers:`` here would quietly
    overrule that.
    """
    values: dict[str, str] = {
        "layer": layer,
        "version": DRAFT_VERSION,
        "intent": _module_intent(
            draft,
            layer=layer,
            layer_is_fallback=layer_is_fallback,
            layer_candidates=layer_candidates,
        ),
        "exports": _list_value(draft.exports),
        "requires": _list_value(draft.requires),
        "uses": _list_value(draft.uses),
        "soft_requires": "none",
        "runtime_only_requires": "none",
        "deferred_requires": _list_value(draft.deferred_requires),
        "exports_helpers": "none",
    }
    lines = [f"module {module_name(draft)}"]
    for field in _MODULE_FIELD_ORDER:
        lines.extend(_field_lines(field, values[field]))
        if field == "exports":
            lines.append("")
    return lines


def module_name(draft: DraftModule) -> str:
    """The flat name this draft declares, which is its file's stem.

    s0ma module names are flat and a source file's stem must equal the
    name it declares (``MODULE_NAME_STEM_MISMATCH``), so a Python
    ``bookshelf.errors`` becomes ``module errors`` in ``errors.s0ma``.
    The harvester's note about the rename says the same thing in the
    same words, from the same rule.
    """
    return Path(draft.source_path).stem


def _module_intent(
    draft: DraftModule,
    *,
    layer: str,
    layer_is_fallback: bool,
    layer_candidates: Sequence[str],
) -> str:
    """The module's ``intent:`` value — lifted if real, else a placeholder."""
    if draft.intent is not None:
        return _quote(draft.intent)

    extra: list[str] = []
    if draft.docstring:
        first_line = draft.docstring.strip().split("\n", 1)[0].strip()
        if first_line:
            extra.append(_DOCSTRING_HINT.format(first_line=_quote_inner(first_line)))
    if layer_is_fallback:
        named = tuple(layer_candidates)
        template = _LAYER_HINT_WITH_CANDIDATES if named else _LAYER_HINT_BARE
        extra.append(
            template.format(
                fallback=layer,
                candidates=_spoken_list(named or _ALL_LAYERS),
            )
        )
    return _quote(placeholder("module", "intent", *extra))


def _module_layer(draft: DraftModule, proposed_layer: str | None) -> tuple[str, bool]:
    """The module's layer, and whether it came from the fallback.

    In order: the caller's proposal, the draft's own layer, the one
    layer every lifted registration agreed on, then
    :data:`FALLBACK_LAYER`. A disagreement between lifted layers cannot
    be honoured — one layer per module is a language rule — so it falls
    through to the fallback, where the placeholder asks for a decision.
    """
    if proposed_layer:
        return proposed_layer, False
    if draft.layer:
        return draft.layer, False
    lifted = {
        declaration.layer for declaration in draft.declarations if declaration.layer
    }
    if len(lifted) == 1:
        return next(iter(lifted)), False
    return FALLBACK_LAYER, True


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def _blocks_in_source_order(
    draft: DraftModule,
) -> list[tuple[int, DraftDeclaration] | DraftUnplaced]:
    """Declarations and un-placeable blocks, interleaved in source order.

    A draft should read like the file it came from, so a carrier sits
    where its text sat. Declarations are wrapped in a ``(start_line,
    declaration)`` tuple purely so the two record types can be told
    apart without a type switch on a frozen dataclass.
    """
    blocks: list[tuple[int, DraftDeclaration] | DraftUnplaced] = [
        (declaration.start_line, declaration) for declaration in draft.declarations
    ]
    blocks.extend(draft.unplaced)
    return sorted(blocks, key=_block_start_line)


def _block_start_line(block: tuple[int, DraftDeclaration] | DraftUnplaced) -> int:
    return block[0] if isinstance(block, tuple) else block.start_line


def _declaration_lines(
    declaration: DraftDeclaration, *, layer: str, draft: DraftModule
) -> list[str]:
    """One declaration: its header line, its fields, ``---`` and its body."""
    if declaration.form == "helper":
        header = f"helper {declaration.name} :: {layer}"
        values = _helper_values(declaration)
    elif declaration.form == "nerve":
        header = f"nerve {declaration.name} :: {layer}"
        values = _nerve_values(declaration, draft=draft)
    else:
        header = f"cell {declaration.name} :: {layer}"
        values = _cell_values(declaration, draft=draft)

    lines = [header]
    order = _FIELD_ORDER[declaration.form]
    for field in order:
        lines.extend(_field_lines(field, values[field]))
    for field, value in values.items():
        if field not in order:
            lines.extend(_field_lines(field, value))
    lines.append(f"{_FIELD_INDENT}---")
    lines.extend(_body_lines(declaration.body))
    return lines


def _helper_values(declaration: DraftDeclaration) -> dict[str, str]:
    """A helper's one field. Not a component contract, so nothing else."""
    values = {
        "intent": _quote(_authored_or_placeholder(declaration, "helper", "intent"))
    }
    values.update(_lifted_extra(declaration, _HELPER_FIELD_ORDER))
    return values


def _nerve_values(declaration: DraftDeclaration, *, draft: DraftModule) -> dict[str, str]:
    """A nerve's fields. Structure is derived; every contract is asked for."""
    values = {
        "kind": "FUNCTION",
        "visibility": _visibility(declaration, draft),
        "intent": _authored_or_placeholder(declaration, "nerve", "intent"),
        "expects": placeholder("nerve", "expects"),
        "guarantees": placeholder("nerve", "guarantees"),
        "forbids": placeholder("nerve", "forbids"),
        "evaluates_at": "FUNCTION_BOUNDARY",
        "provides": "none",
        "returns": "none",
        "raises": "none",
        "interface": "none",
        "latency_ms": "none",
        "depends_on": "none",
        "internal": "none",
        "expected_exceptions": "none",
        "consumes_via_dict": "none",
        "declares_attributes": "none",
        "covered_by": "none",
    }
    for field, text in declaration.fields:
        values[field] = _render_lifted(field, text)
    values["intent"] = _quote_if_prose("intent", values["intent"])
    values["expects"] = _quote_if_prose("expects", values["expects"])
    values["guarantees"] = _quote_if_prose("guarantees", values["guarantees"])
    values["forbids"] = _quote_if_prose("forbids", values["forbids"])
    return values


def _cell_values(declaration: DraftDeclaration, *, draft: DraftModule) -> dict[str, str]:
    """A cell's fields, with the kind reconciled against the body's shape."""
    kind, override = _cell_kind(declaration)
    extra = [override] if override else []
    values = {
        "kind": kind,
        "visibility": _visibility(declaration, draft),
        "intent": _authored_or_placeholder(declaration, "cell", "intent", *extra),
        "schema": placeholder("cell", "schema"),
        "invariants": "none",
        "covered_by": "none",
    }
    for field, text in declaration.fields:
        values[field] = _render_lifted(field, text)
    values["intent"] = _quote_if_prose("intent", values["intent"])
    values["schema"] = _quote_if_prose("schema", values["schema"])
    return values


def _authored_or_placeholder(
    declaration: DraftDeclaration, form: str, field: str, *extra: str
) -> str:
    """The lifted authored value when there is one, else the placeholder.

    An intent somebody wrote is real and is carried over word for word.
    The emitter never overwrites one, and never invents one.
    """
    if field == "intent" and declaration.intent is not None:
        return declaration.intent
    return placeholder(form, field, *extra)


def _visibility(declaration: DraftDeclaration, draft: DraftModule) -> str:
    """``PUBLIC`` for a name this module exports, ``INTERNAL`` otherwise.

    This is the Python convention read back, not a judgement: a module
    with an ``__all__`` has already said which names are public, and a
    module without one says it with the leading underscore that the
    harvester used to tell a nerve from a helper.
    """
    return "PUBLIC" if declaration.name in draft.exports else "INTERNAL"


def _cell_kind(declaration: DraftDeclaration) -> tuple[str, str]:
    """The cell kind to write, plus a sentence when it had to be changed.

    The harvester's kind is a hint read off the class's bases and
    decorators, and a hint can contradict the body: a ``Protocol`` reads
    as ``TYPE``, but a ``TYPE`` cell must hold a type alias and a
    ``Protocol`` is a class, so writing ``TYPE`` would produce a draft
    that does not parse. Where hint and body disagree the body wins —
    it is the fact — and the reason is written into the cell's intent
    placeholder, where the author will see it and ``s0ma check`` already
    refuses.
    """
    hinted = declaration.kind or "MODEL"
    shape = _body_shape(declaration.body)
    if shape == "class" and hinted in _VALUE_KINDS:
        return "MODEL", _KIND_OVERRIDE_HINT.format(
            used="MODEL", hinted=hinted, shape=_SHAPE_WORDS["class"]
        )
    if shape == "value" and hinted in _CLASS_KINDS:
        return "CONSTANT", _KIND_OVERRIDE_HINT.format(
            used="CONSTANT", hinted=hinted, shape=_SHAPE_WORDS["value"]
        )
    return hinted, ""


def _body_shape(body: str) -> str:
    """``"class"``, ``"value"`` or ``"other"`` for a body's first statement.

    The same three-way split ``body_extractor._validate_cell_body``
    makes, re-read here from the body text rather than imported, because
    that function reports diagnostics rather than returning a shape.
    """
    try:
        parsed = ast.parse(body)
    except SyntaxError:  # pragma: no cover - the harvester parsed it already
        return "other"
    if not parsed.body:  # pragma: no cover - a declaration always has a body
        return "other"
    first = parsed.body[0]
    if isinstance(first, ast.ClassDef):
        return "class"
    if isinstance(first, (ast.Assign, ast.AnnAssign)):
        return "value"
    return "other"


def _lifted_extra(
    declaration: DraftDeclaration, order: tuple[str, ...]
) -> dict[str, str]:
    """Lifted fields that have no slot in *order*, rendered for emission."""
    return {
        field: _render_lifted(field, text)
        for field, text in declaration.fields
        if field not in order
    }


def _render_lifted(field: str, text: str) -> str:
    """One lifted ``@component`` field, ready to write after ``<field>:``."""
    return _quote(text) if field in _QUOTED_FIELDS else text


def _quote_if_prose(field: str, value: str) -> str:
    """Quote *value* unless a lifted renderer already quoted it."""
    if field in _QUOTED_FIELDS and not value.startswith('"'):
        return _quote(value)
    return value


# ---------------------------------------------------------------------------
# The un-placeable-source carrier
# ---------------------------------------------------------------------------


def _carrier_lines(
    block: DraftUnplaced, *, layer: str, draft: DraftModule
) -> list[str]:
    """One carrier cell for text the harvester could not place.

    Every part of the shape comes from :mod:`s0ma_dsl.adopt.harvest`, so
    the emitter cannot drift from the checker that has to recognise it.
    """
    name = unplaced_cell_name(block)
    lines = [f"cell {name} :: {layer}"]
    values = {
        "kind": UNPLACED_CELL_KIND,
        "visibility": UNPLACED_CELL_VISIBILITY,
        "intent": _quote(UNPLACED_CELL_INTENT),
        "schema": _quote(unplaced_cell_schema(block, draft.source_path)),
        "invariants": "none",
        "covered_by": "none",
    }
    for field in _CELL_FIELD_ORDER:
        lines.extend(_field_lines(field, values[field]))
    lines.append(f"{_FIELD_INDENT}---")
    lines.extend(_body_lines(f"{name} = {render_unplaced_value(block.text)}\n"))
    return lines


# ---------------------------------------------------------------------------
# Rendering primitives
# ---------------------------------------------------------------------------


def _field_lines(field: str, value: str) -> list[str]:
    """``    <field>: <value>``, or the block-list form for a long list."""
    if value.startswith("\n"):
        return [f"{_FIELD_INDENT}{field}:", *value.lstrip("\n").split("\n")]
    return [f"{_FIELD_INDENT}{field}: {value}"]


def _list_value(entries: Sequence[str]) -> str:
    """A list field's value: ``none``, an inline list, or a block list.

    The block form is signalled to :func:`_field_lines` by a leading
    newline, because the two forms differ in shape and not only in text:
    an inline list rides on the field's own line and a block list does
    not.
    """
    if not entries:
        return "none"
    if len(entries) <= INLINE_LIST_MAX:
        return "[" + ", ".join(entries) + "]"
    return "\n" + "\n".join(f"      - {entry}" for entry in entries)


def _body_lines(body: str) -> list[str]:
    """The body, verbatim, with one body indent added to every line.

    A line that is empty stays empty; every other line — a line of only
    whitespace included — is shifted right by exactly the body indent
    the parser will take back. Nothing else happens to the text.
    """
    text = body[:-1] if body.endswith("\n") else body
    return [(_BODY_INDENT + line) if line else "" for line in text.split("\n")]


def _note_comments(notes: Sequence[str]) -> list[str]:
    """The harvester's notes, as wrapped comment lines under the provenance.

    Notes are advice for whoever finishes the draft, not debt the
    compiler has to see, so a comment is the right home for them — and
    the top of the file is the only place a comment is safe: a comment
    *between* declarations would be swallowed into the preceding body by
    the declaration splitter, which would change that body.
    """
    lines: list[str] = []
    for note in notes:
        wrapped = textwrap.wrap(note, width=88) or [""]
        lines.append(f"# note: {wrapped[0]}")
        lines.extend(f"#   {piece}" for piece in wrapped[1:])
    return lines


def _quote(text: str) -> str:
    """*text* as a ``.s0ma`` quoted string.

    Two substitutions, both forced by the grammar and both applied to
    prose only, never to carried code: a double quote becomes a single
    quote (``QUOTED_STRING`` runs to the next ``"``, so there is no
    escape), and any run of whitespace — a newline included — becomes
    one space, because a field value is one line.
    """
    return f'"{_quote_inner(text)}"'


def _quote_inner(text: str) -> str:
    """The inside of a quoted string: no double quote, no line break."""
    return " ".join(text.replace('"', "'").split())


def _spoken_list(items: Sequence[str]) -> str:
    """``a``, ``a or b``, ``a, b or c`` — a list a person reads aloud."""
    if not items:  # pragma: no cover - callers always pass at least one
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" or {items[-1]}"
