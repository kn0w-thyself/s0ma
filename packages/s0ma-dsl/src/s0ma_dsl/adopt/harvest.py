"""Harvest — read one Python module and derive the structural half of a draft.

This is the mechanical step of rung 3. It reads a plain-Python file with
:mod:`ast`, never imports it and never runs it (retrofit rule R-1), and
returns a :class:`~s0ma_dsl.adopt.model.DraftModule`: what the file *is*,
never what it *means*. Every piece of authored meaning the file does not
already carry is left as ``None`` for the draft emitter to turn into a
``FIXME(adopt):`` placeholder that ``s0ma check`` refuses (ruling D-3 and
R-5). Nothing here guesses an intent.

Bodies are copied **verbatim by line range from the file's own text**,
never regenerated with ``ast.unparse``, so comments, blank lines,
formatting and string quoting survive the trip exactly as the author
wrote them.

Public surface
--------------

``harvest_module(root, source, *, layer, s0ma_modules, first_party)``
    The one entry point: a :class:`SourceFile` in, a ``DraftModule`` out.

``account_lines(draft, source_text)``
    The proof that nothing was lost: one owner label per source line.

``unplaced_cell_name`` / ``unplaced_cell_schema`` / ``render_unplaced_value``
    The unplaced-carrier contract (below), as three pure functions so the
    draft emitter (D2) and the placeholder checker (D3) read the same
    rules from one place instead of each re-deriving them.

``HarvestError``
    Raised when the file cannot be read or parsed. The harvester never
    returns a half-built draft.


The unplaced carrier — decision, alternatives, evidence
-------------------------------------------------------

**The problem.** Some top-level Python has no declaration form: a module
-level ``logger = logging.getLogger(__name__)``, an ``if __name__ ==
"__main__":`` block, a ``for`` loop that fills a table at import time. It
must be carried into the draft — nothing is allowed to go missing — and
the compiler must be able to *see* it, because ``ADOPT_UNPLACED_CODE``
(D3) has to refuse the build until a person has placed it. A comment is
invisible to the parser, so a comment cannot be the carrier.

**The decision.** One ``cell`` per unplaced block, of ``kind: CONSTANT``
and ``visibility: INTERNAL``, named ``ADOPT_UNPLACED_<start>_<end>``,
whose ``schema:`` field opens with the marker
:data:`~s0ma_dsl.adopt.model.DRAFT_UNPLACED_MARKER` (``adopt: unplaced``)
and whose body assigns that same name a **string literal holding the
source text verbatim**::

    cell ADOPT_UNPLACED_0010_0011 :: INFRASTRUCTURE
        kind: CONSTANT
        visibility: INTERNAL
        intent: "Source the retrofit could not place. Move it into a declaration, then delete this."
        schema: "adopt: unplaced - src/bookshelf/storage.py lines 10-11 - a module-level assignment"
        invariants: none
        covered_by: none
        ---
        ADOPT_UNPLACED_0010_0011 = r\"\"\"logger = logging.getLogger(__name__)
        logger.addHandler(logging.NullHandler())
        \"\"\"

D3 fires ``ADOPT_UNPLACED_CODE`` when a cell's name starts with
:data:`UNPLACED_CELL_PREFIX` **or** any authored field of a declaration
carries ``DRAFT_UNPLACED_MARKER`` — two independent keys, so editing one
away does not silence the refusal.

Why this one, against the four criteria:

(a) *It parses today.* Proven, not assumed: ``test_adopt_harvest.py``
    runs the real parser and the real intra-module validator over a
    hand-written ``.s0ma`` file built from this carrier and asserts zero
    diagnostics. ``kind: CONSTANT`` requires the body's first statement
    to be an assignment (``parser/body_extractor.py:527``) and the cell
    name to equal the assigned identifier (``CONSTANT_NAME_MISMATCH``) —
    both hold by construction.
(b) *A semantic check can detect it reliably.* The name and the
    ``schema:`` text both ride the IR as authored fields; neither is a
    comment, neither is dropped by the parser.
(c) *It cannot be mistaken for finished work.* The text is quarantined
    as **data**: a string literal executes nothing, so no reader and no
    runtime can mistake it for code that runs. The name shouts, the
    marker shouts, and the build refuses.
(d) *It loses no text.* Bodies are indented by the body indent and the
    parser dedents by exactly that amount
    (``parser/body_extractor.py:127``), so the literal's value is the
    original text byte for byte. :func:`render_unplaced_value` picks the
    literal form that survives the round trip for *any* input, and the
    tests prove it with ``ast.literal_eval`` over hostile cases: text
    containing ``\"\"\"``, text ending in a quote or a backslash, text
    with a line of only whitespace, a line reading ``---``, a line that
    looks like a declaration header, embedded imports, and non-ASCII.

Rejected, with the evidence that rejected them:

* **A comment** (``# adopt: unplaced ...``). Stripped by the splitter
  (``_COMMENT_RE``, ``parser/s0ma_parser.py:192``) and absent from the
  IR. Fails (b) outright — this is the reason the milestone asks the
  question.
* **``metadata:`` on the module header.** It *parses* (unknown module
  fields are tolerated) but ``_build_module`` never reads it and
  ``module`` has no ``metadata`` row in ``FIELD_CLASSIFICATIONS``
  (``semantic_state.py:106``), so the value is silently dropped: the
  compiler cannot see it. Fails (b). Also fails (d) for multi-line text:
  metadata values are single-line scalars.
* **``metadata:`` on the carrier cell.** Visible and structured, but it
  buys nothing the name and ``schema:`` do not already give, and a
  metadata map cannot hold multi-line text either. Not used, so the
  carrier stays inside the fields every cell already has.
* **A ``helper`` whose body is the raw statements.** Refused at parse
  time: ``PARSE_ERROR``, "body must be a function or class definition,
  found assignment" (``_validate_helper_body``). Wrapping the statements
  in a ``def`` to get past that would re-indent them (fails (d)), change
  what they mean, and break outright on text that is not legal inside a
  function.
* **A cell carrying the raw statements as live code** — either a
  ``CONSTANT`` cell whose body opens with a marker assignment, or a
  ``kind: FRAMEWORK`` cell (the one cell kind with no body-shape rule).
  Both parse. Both were rejected on (c): the text stays *executable*, so
  a reader or a later edit can mistake it for finished work, and the
  emitted module would silently run it if the refusal were ever lost.
  They also collect unrelated diagnostics that confuse the real message
  — ``BARE_IMPORT`` for any import inside the block
  (``_check_bare_imports`` walks the whole body tree),
  ``PROHIBITED_CONSTRUCT`` for ``eval``/``exec`` — and ``kind:
  FRAMEWORK`` means "s0ma's own infrastructure" (spec §3.1), which this
  is not.
* **The language's own debt marker, ``pending("reason")``.** It is the
  right shape for *missing* meaning but the wrong shape here: it carries
  a reason, not the text, so it fails (d); and ``SEMANTIC_PENDING_DEBT``
  is a warning in migration and dev mode (``config.py``), which ruling
  R-5 forbids for a draft artifact.

No existing ``.s0ma`` file in the repository contains ``ADOPT_UNPLACED``
or ``adopt: unplaced`` (144 files searched), so D3 can key on both
without disturbing the corpus.


What is *not* placeable, and why
--------------------------------

Everything below is carried verbatim into ``unplaced`` with a plain
reason. None of it is dropped and none of it is guessed at:

* a module-level assignment whose name is not an upper-case constant
  (``logger = logging.getLogger(__name__)``) — a value computed at
  import time has no declaration form;
* a module-level assignment with several targets or a non-name target
  (``A = B = 1``, ``obj.attr = 1``);
* an ``if __name__ == "__main__":`` block — a s0ma project names its
  entry points in ``[tool.s0ma] bootstrap_files``;
* an ``if TYPE_CHECKING:`` block that imports anything but the standard
  library — see the next section, which is the whole rule;
* any other conditional or guarded top-level statement (``if``,
  ``try``, ``with``, ``for``, ``while``, ``match``);
* a bare top-level expression or call (``configure_logging()``),
  ``del``, ``global``, ``assert``, ``raise`` at module level;
* a ``from __future__ import ...`` line is the one exception: it is an
  import, so it is accounted as a header fact, but it has no header home
  (s0ma's transpiler writes the generated file's import block itself and
  a future import must be that file's first statement), so it is dropped
  with a note naming it rather than carried.


``if TYPE_CHECKING:`` — promoted when it is standard library only
-----------------------------------------------------------------

s0ma has no type-only import form and the emitted module carries no
``from __future__ import annotations``, so an import that moves out of a
``TYPE_CHECKING`` guard and into ``requires:`` really does run when the
module loads. For a first-party import that can close an import cycle
the guard was holding open; for a third-party one it can turn an
optional dependency into a hard one. Those blocks therefore stay
un-placeable, carried verbatim, with a reason that names the first
import which kept them there so the person deciding knows what to look
at.

A block whose imports are **all** standard library is promoted instead:
the imports join ``requires:`` like any other load-time import, the
block's lines are accounted as ``header:import`` rather than as an
un-placeable block, and one note on the draft says what was done and why
it is safe. Importing ``collections.abc`` or ``pathlib`` when the module
loads costs nothing measurable and cannot reach back into this project,
so no cycle can close. This is worth mechanising rather than leaving to
a person: harvesting the 493 Python files under ``packages/`` produced
383 un-placeable blocks and 248 of them — 65% — were ``TYPE_CHECKING``
guards (friction F-D1-3; milestone D1b).

A block qualifies only when all four of these hold:

1. the test is exactly ``TYPE_CHECKING`` or ``<something>.TYPE_CHECKING``
   (a ``if not TYPE_CHECKING:`` runtime fallback is not the same thing
   and is never promoted);
2. there is no ``else:`` branch — that branch runs at import time and
   has to be read by a person;
3. every statement in the body is an ``import`` or ``from ... import``;
4. every one of those imports names a top-level module in
   :data:`sys.stdlib_module_names`. A relative import (``from . import
   x``, ``from ..pkg import y``) is first-party by definition and is
   never promoted, whatever it reaches.

Two consequences worth knowing. First, a promoted import is **not**
dropped by the "imported but never used" filter that the other header
imports pass through: a type-only import is by definition used in a type
position, and the reference scan reads bodies with :mod:`ast`, so it
cannot see a name inside a *quoted* annotation. Calling such an import
unused would delete the one thing a person needs the moment they unquote
that annotation, and the import is standard library, so keeping it costs
nothing. Second, the rule reads ``sys.stdlib_module_names`` alone and
never the project's own module list, because :func:`account_lines`
audits the same decision from the source text and is not given one. A
project carrying a top-level module of its own that shadows a standard
-library name (its own ``types.py``) would therefore have such an import
promoted; that is the one case this rule gets wrong. ``adopt/graph.py``
checks first-party *before* stdlib for exactly that reason, and a
project in that shape should read the promotion note rather than trust
it.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.model import (
    DRAFT_UNPLACED_MARKER,
    DraftDeclaration,
    DraftModule,
    DraftUnplaced,
)
from s0ma_dsl.adoption import compute_adopted_hash

if TYPE_CHECKING:  # pragma: no cover - typing only
    from s0ma_dsl.adopt.model import SourceFile

__all__ = [
    "HarvestError",
    "LINE_GAP",
    "LINE_UNACCOUNTED",
    "UNPLACED_CELL_KIND",
    "UNPLACED_CELL_PREFIX",
    "UNPLACED_CELL_VISIBILITY",
    "account_lines",
    "harvest_module",
    "render_unplaced_value",
    "unplaced_cell_name",
    "unplaced_cell_schema",
]


# ---------------------------------------------------------------------------
# The unplaced-carrier contract (D1.T3) — see the module docstring
# ---------------------------------------------------------------------------

UNPLACED_CELL_PREFIX = "ADOPT_UNPLACED_"
"""Name prefix of the cell that carries un-placeable source text.

One of the two keys ``ADOPT_UNPLACED_CODE`` matches on; the other is
:data:`~s0ma_dsl.adopt.model.DRAFT_UNPLACED_MARKER` in the cell's
``schema:``. Part of the ``@1`` contract: the emitter writes it and the
checker matches it, so changing the spelling is a breaking change.
"""

UNPLACED_CELL_KIND = "CONSTANT"
"""Cell kind of the unplaced carrier: the text rides as an inert value."""

UNPLACED_CELL_VISIBILITY = "INTERNAL"
"""Visibility of the unplaced carrier: never part of a public surface."""


# ---------------------------------------------------------------------------
# Line-accounting labels
# ---------------------------------------------------------------------------

LINE_GAP = "gap"
"""Owner label for a line that is blank or holds only a comment."""

LINE_UNACCOUNTED = "unaccounted"
"""Owner label for a line nothing claimed — always a bug, never expected."""

_LINE_DOCSTRING = "header:docstring"
_LINE_IMPORT = "header:import"
_LINE_EXPORTS = "header:exports"
_DECLARATION_PREFIX = "declaration:"
_UNPLACED_PREFIX = "unplaced:"
_CONFLICT_PREFIX = "conflict:"

_TYPE_CHECKING = "TYPE_CHECKING"
"""The guard name, spelled once: the recogniser and the promotion rule
(D1b) must read the same word."""


class HarvestError(Exception):
    """A module could not be read or parsed, so no draft was built.

    Carries the project-relative path, the 1-based line when the failure
    has one, and one plain sentence a command line can print as-is.
    """

    def __init__(self, path: str, message: str, line: int | None = None) -> None:
        self.path = path
        self.line = line
        self.message = message
        super().__init__(f"{path}: {message}" if line is None else f"{path}:{line}: {message}")


# ---------------------------------------------------------------------------
# Small internal records (not part of the frozen §5.2 model)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ImportFact:
    """One top-level or function-scoped import, as the harvester needs it."""

    entry: str
    """The ``requires:``-shaped entry text that reproduces this import."""

    target: str
    """The dotted module the import reaches, relative forms resolved."""

    bound: tuple[str, ...]
    """The names the statement binds into the module namespace."""

    members: tuple[str, ...]
    """The member names taken from the target, empty for a plain import."""

    line: int
    end_line: int
    deferred: bool
    future: bool

    promoted: bool = False
    """Whether this import was lifted out of a standard-library-only
    ``if TYPE_CHECKING:`` block. A promoted import skips the
    imported-but-never-used filter — see the module docstring."""


@dataclass(frozen=True, slots=True)
class _Accounted:
    """One accounted top-level range, before it becomes a draft record."""

    start: int
    end: int


# ---------------------------------------------------------------------------
# The carrier, as three pure functions
# ---------------------------------------------------------------------------


def unplaced_cell_name(block: DraftUnplaced) -> str:
    """Name of the cell that carries *block* in the emitted ``.s0ma`` file.

    ``ADOPT_UNPLACED_<start>_<end>``, line numbers zero-padded to four
    digits so the carriers sort in source order in any listing. Two
    blocks of one module can never collide: their line ranges differ.
    """
    return f"{UNPLACED_CELL_PREFIX}{block.start_line:04d}_{block.end_line:04d}"


def unplaced_cell_schema(block: DraftUnplaced, source_path: str) -> str:
    """The carrier cell's ``schema:`` text, opening with the marker.

    One line, plain language, and machine-readable at the front: the
    marker, then where the text came from, then why it could not be
    placed. *source_path* is the project-relative POSIX path of the
    Python file the text was read from.

    A ``.s0ma`` quoted string has no escape for a double quote (the
    grammar's ``QUOTED_STRING`` runs to the next ``"``), so any double
    quote in the reason becomes a single quote. That is cosmetic — the
    carried text itself is never touched.
    """
    span = (
        f"line {block.start_line}"
        if block.start_line == block.end_line
        else f"lines {block.start_line}-{block.end_line}"
    )
    text = f"{DRAFT_UNPLACED_MARKER} - {source_path} {span} - {block.reason}"
    return text.replace('"', "'")


def render_unplaced_value(text: str) -> str:
    """Render *text* as the Python literal the carrier cell assigns.

    Two forms, chosen so the round trip is exact for every possible
    input:

    * a raw triple-quoted string when the text can survive one — the
      readable form, in which the code still looks like code;
    * otherwise a parenthesised run of one ``repr()`` per line, which is
      immune to quoting *and* to indentation because each line is its
      own literal.

    The fallback is taken when the text contains ``\"\"\"``, ends with a
    quote or a backslash, holds a carriage return or a null, or holds a
    line made only of whitespace (the emitter writes blank body lines
    blank, which would trim such a line away). Whatever the form, the
    value is the text unchanged — the tests prove it with
    ``ast.literal_eval``.
    """
    if not text:
        return '""'
    if _raw_string_is_safe(text):
        return f'r"""{text}"""'
    lines = text.splitlines(keepends=True)
    rendered = "".join(f"    {line!r}\n" for line in lines)
    return f"(\n{rendered})"


def _raw_string_is_safe(text: str) -> bool:
    """Whether *text* survives a raw triple-quoted literal unchanged."""
    if '"""' in text or text.endswith('"') or text.endswith("\\"):
        return False
    if "\r" in text or "\x00" in text:
        return False
    return all(line == "" or line.strip() != "" for line in text.split("\n"))


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def harvest_module(
    root: Path,
    source: SourceFile,
    *,
    layer: str | None = None,
    s0ma_modules: frozenset[str] = frozenset(),
    first_party: frozenset[str] = frozenset(),
) -> DraftModule:
    """Read one Python file and derive the structural half of its draft.

    The file is read as UTF-8 text and parsed with :mod:`ast`. It is
    never imported and never executed (rule R-1), and nothing is written
    anywhere.

    Args:
        root: The project root. The file read is ``root / source.path``.
        source: The discovered file to harvest. ``source.path`` is
            project-relative and POSIX-shaped; ``source.module`` is its
            dotted import name.
        layer: The module's single layer (one layer per module is a
            language rule). Pass the ``--layer`` argument or a
            high-confidence proposal; leave it ``None`` and the emitter
            writes a placeholder that asks. A layer lifted from a
            registered ``@component`` wins over ``None`` but never over
            an explicit argument.
        s0ma_modules: Dotted names of first-party modules that already
            exist as ``.s0ma`` sources. An import reaching one of these
            becomes a ``uses:`` entry; an import reaching a first-party
            module that is *not* here becomes a ``requires:`` entry plus
            a note, because converting leaf-first is what makes that
            rare. The command line supplies this set; the harvester does
            not go looking for it.
        first_party: Dotted names of every module in this project.
            Used to tell "another module of ours" from a third-party
            package without importing anything.

    Returns:
        A :class:`DraftModule` whose ``declarations`` and ``unplaced``
        blocks account for every line of the file exactly once — see
        :func:`account_lines`, which proves it.

    Raises:
        HarvestError: The file is unreadable, is not UTF-8, or is not
            valid Python.
    """
    path = root / Path(source.path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarvestError(source.path, f"the file could not be read ({exc.strerror}).") from exc
    except UnicodeDecodeError as exc:
        raise HarvestError(
            source.path,
            "the file is not UTF-8 text, so it cannot be read without guessing at its encoding.",
        ) from exc

    try:
        tree = ast.parse(text, filename=source.path)
    except SyntaxError as exc:
        raise HarvestError(
            source.path,
            f"the file is not valid Python, so there is nothing to draft ({exc.msg}).",
            line=exc.lineno,
        ) from exc

    lines = text.splitlines(keepends=True)
    notes: list[str] = []

    module_name = Path(source.path).stem
    if "." in source.module:
        notes.append(
            f"s0ma module names are flat, so this draft declares `module {module_name}` "
            f"rather than `{source.module}`. Every module name in a project must be "
            "unique; rename the draft if another module already carries this name."
        )

    docstring_range = _docstring_range(tree)
    imports, import_ranges, promoted_ranges = _collect_imports(tree, source.module)
    exports_literal, exports_ranges = _collect_dunder_all(tree)

    consumed = set(import_ranges) | set(promoted_ranges) | set(exports_ranges)
    if docstring_range is not None:
        consumed.add(docstring_range)

    declarations, unplaced_blocks, gap_notes = _split_body(
        tree,
        lines,
        consumed=consumed,
        layer=layer,
        notes=notes,
    )

    referenced = _referenced_names(declarations, unplaced_blocks)
    requires, deferred_requires, uses, import_notes = _header_dependencies(
        imports,
        referenced=referenced,
        s0ma_modules=s0ma_modules,
        first_party=first_party,
    )
    notes.extend(_promotion_note(start, end) for start, end in promoted_ranges)
    notes.extend(import_notes)
    notes.extend(gap_notes)

    exports, export_notes = _exports(exports_literal, declarations)
    notes.extend(export_notes)

    module_layer = layer
    if module_layer is None:
        lifted = [declaration.layer for declaration in declarations if declaration.layer]
        if lifted and len(set(lifted)) == 1:
            module_layer = lifted[0]
        elif len(set(lifted)) > 1:
            notes.append(
                "The registered components in this file name more than one layer ("
                + ", ".join(sorted(set(lifted)))
                + "). All components in a module must share the module's layer, so "
                "pick one and move the others to their own module."
            )

    return DraftModule(
        module=module_name,
        source_path=source.path,
        source_hash=compute_adopted_hash(path),
        layer=module_layer,
        intent=None,
        docstring=ast.get_docstring(tree, clean=False),
        requires=requires,
        deferred_requires=deferred_requires,
        uses=uses,
        exports=exports,
        declarations=tuple(declarations),
        unplaced=tuple(unplaced_blocks),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Header facts
# ---------------------------------------------------------------------------


def _docstring_range(tree: ast.Module) -> tuple[int, int] | None:
    """The module docstring's line range, or ``None`` when there is none."""
    if not tree.body:
        return None
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return (first.lineno, _end_line(first))
    return None


def _collect_imports(
    tree: ast.Module, dotted_module: str
) -> tuple[tuple[_ImportFact, ...], tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    """Every import in the file, plus the header ranges it consumed.

    Top-level imports are header facts. Imports inside a function or a
    method are deferred imports and become ``deferred_requires:``; they
    live inside a declaration's own line range, so they are not returned
    as header ranges.

    A standard-library-only ``if TYPE_CHECKING:`` block is a header fact
    too (D1b, module docstring): its imports come back as ordinary
    load-time facts flagged ``promoted``, and the whole block's line
    range is returned separately so the draft can say in a note what was
    absorbed.
    """
    package = dotted_module.rpartition(".")[0]
    facts: list[_ImportFact] = []
    ranges: list[tuple[int, int]] = []
    promoted: list[tuple[int, int]] = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            facts.extend(_import_facts(node, package, deferred=False))
            ranges.append((node.lineno, _end_line(node)))
        elif isinstance(node, ast.If) and _is_type_checking_guard(node):
            lifted, blocker = _type_checking_promotion(node)
            if blocker is not None:
                continue
            for guarded in lifted:
                facts.extend(_import_facts(guarded, package, deferred=False, promoted=True))
            promoted.append((node.lineno, _end_line(node)))

    for walked in ast.walk(tree):
        if not isinstance(walked, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(walked):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                facts.extend(_import_facts(inner, package, deferred=True))

    return tuple(facts), tuple(ranges), tuple(promoted)


def _import_facts(
    node: ast.Import | ast.ImportFrom, package: str, *, deferred: bool, promoted: bool = False
) -> list[_ImportFact]:
    """Turn one import statement into one fact per imported target."""
    end = _end_line(node)
    facts: list[_ImportFact] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            entry = alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
            bound = alias.asname if alias.asname else alias.name.split(".")[0]
            facts.append(
                _ImportFact(
                    entry=entry,
                    target=alias.name,
                    bound=(bound,),
                    members=(),
                    line=node.lineno,
                    end_line=end,
                    deferred=deferred,
                    future=alias.name == "__future__",
                    promoted=promoted,
                )
            )
        return facts

    target = _resolve_relative(node, package)
    for alias in node.names:
        member = alias.name
        entry = f"{target}:{member}"
        if alias.asname is not None:
            entry = f"{entry} as {alias.asname}"
        facts.append(
            _ImportFact(
                entry=entry,
                target=target,
                bound=(alias.asname or member,),
                members=(member,),
                line=node.lineno,
                end_line=end,
                deferred=deferred,
                future=target == "__future__",
                promoted=promoted,
            )
        )
    return facts


def _resolve_relative(node: ast.ImportFrom, package: str) -> str:
    """Resolve ``from . import x`` / ``from .mod import x`` to a dotted name."""
    if not node.level:
        return node.module or ""
    parts = package.split(".") if package else []
    climb = node.level - 1
    base = parts[: len(parts) - climb] if climb else parts
    pieces = [piece for piece in (*base, node.module or "") if piece]
    return ".".join(pieces)


def _collect_dunder_all(
    tree: ast.Module,
) -> tuple[tuple[str, ...] | None, tuple[tuple[int, int], ...]]:
    """The literal ``__all__``, in declared order, and its line range."""
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        names: list[str] = []
        if isinstance(value, (ast.List, ast.Tuple)):
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    names.append(element.value)
        return tuple(names), ((node.lineno, _end_line(node)),)
    return None, ()


def _exports(
    declared: tuple[str, ...] | None, declarations: list[DraftDeclaration]
) -> tuple[tuple[str, ...], list[str]]:
    """The ``exports:`` list, and notes for anything it cannot name."""
    public = [
        declaration.name for declaration in declarations if declaration.form in ("nerve", "cell")
    ]
    if declared is None:
        return tuple(name for name in public if not name.startswith("_")), []

    exportable = set(public)
    every = {declaration.name for declaration in declarations}
    kept = [name for name in declared if name in exportable]
    missing = [name for name in declared if name not in every]
    private = [name for name in declared if name in every and name not in exportable]
    notes: list[str] = []
    if missing:
        notes.append(
            "The file's __all__ names "
            + ", ".join(missing)
            + ", which this draft has no declaration for. A module can only export what "
            "it declares, so those names are left out of exports: — place the code they "
            "came from first, then add them back."
        )
    if private:
        notes.append(
            "The file's __all__ names "
            + ", ".join(private)
            + ", which this draft makes a helper. Helpers are private to their module, so "
            "they are left out of exports: — promote one to a nerve if it really is part "
            "of the public surface."
        )
    return tuple(kept), notes


def _header_dependencies(
    imports: tuple[_ImportFact, ...],
    *,
    referenced: frozenset[str],
    s0ma_modules: frozenset[str],
    first_party: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], list[str]]:
    """Sort every import into ``requires`` / ``deferred_requires`` / ``uses``.

    An import no body mentions is left out and named in a note — except
    an import promoted out of a ``TYPE_CHECKING`` block, which is kept
    whether or not a body mentions it, because a type-only import can be
    used inside a quoted annotation that :func:`_referenced_names`
    cannot read (module docstring, D1b).
    """
    requires: set[str] = set()
    deferred: set[str] = set()
    uses: set[str] = set()
    notes: list[str] = []
    unused: list[str] = []
    future: list[str] = []
    not_converted: set[str] = set()
    plain_first_party: set[str] = set()
    deferred_first_party: set[str] = set()

    for fact in sorted(imports, key=lambda f: (f.line, f.entry)):
        if fact.future:
            if not fact.deferred:
                future.append(fact.entry)
            continue
        if not fact.promoted and not any(name in referenced for name in fact.bound):
            if not fact.deferred:
                unused.append(fact.entry)
            continue

        resolved = _first_party_target(fact, first_party)
        if resolved is not None and resolved in s0ma_modules and not fact.deferred:
            flat = resolved.rpartition(".")[2]
            if fact.members:
                uses.update(f"{flat}.{member}" for member in fact.members)
            else:
                plain_first_party.add(resolved)
                requires.add(fact.entry)
            continue
        if resolved is not None and resolved not in s0ma_modules:
            not_converted.add(resolved)
        elif resolved is not None and fact.deferred:
            deferred_first_party.add(resolved)
        if fact.deferred:
            deferred.add(fact.entry)
        else:
            requires.add(fact.entry)

    deferred -= requires

    if future:
        notes.append(
            "The file's `from __future__ import annotations` line is not carried into the "
            "draft: s0ma writes the generated file's import block itself, and a future "
            "import has to be the first statement of a file. Annotations are therefore "
            "evaluated as they are written — quote any annotation that names something "
            "defined later in the file."
        )
    if unused:
        notes.append(
            "Imported but never used, so left out of the header: " + ", ".join(sorted(unused)) + "."
        )
    for target in sorted(not_converted):
        notes.append(
            f"`{target}` is another module of this project that is not a .s0ma module yet, "
            "so it is declared as a plain Python import rather than as a uses: entry. "
            "Convert leaf-first and move it to uses: once that module is converted."
        )
    for target in sorted(plain_first_party):
        notes.append(
            f"`{target}` is imported whole (`import {target}`) rather than by name. A "
            "uses: entry names one component, so this stays a requires: entry; to move "
            "it to uses:, import the names the bodies actually use."
        )
    for target in sorted(deferred_first_party):
        notes.append(
            f"`{target}` is already a .s0ma module, but this file imports it inside a "
            "function. There is no deferred form of uses:, so it stays a "
            "deferred_requires: entry reaching the built Python module. Move it to uses: "
            "if the import does not need to be deferred."
        )

    return tuple(sorted(requires)), tuple(sorted(deferred)), tuple(sorted(uses)), notes


def _first_party_target(fact: _ImportFact, first_party: frozenset[str]) -> str | None:
    """The first-party module this import reaches, by longest-prefix match."""
    if not fact.target:
        return None
    for member in fact.members:
        candidate = f"{fact.target}.{member}"
        if candidate in first_party:
            return candidate
    if fact.target in first_party:
        return fact.target
    return None


# ---------------------------------------------------------------------------
# Declarations and unplaced blocks
# ---------------------------------------------------------------------------


def _split_body(
    tree: ast.Module,
    lines: list[str],
    *,
    consumed: set[tuple[int, int]],
    layer: str | None,
    notes: list[str],
) -> tuple[list[DraftDeclaration], list[DraftUnplaced], list[str]]:
    """Turn the file's top-level statements into declarations and blocks."""
    claimed: list[_Accounted] = [_Accounted(start, end) for start, end in sorted(consumed)]
    declarations: list[DraftDeclaration] = []
    raw_unplaced: list[tuple[int, int, str]] = []

    for node in tree.body:
        span = (node.lineno, _end_line(node))
        if span in consumed:
            continue
        start = _attach_comment_block(lines, _statement_start(node), claimed)
        end = span[1]
        claimed.append(_Accounted(start, end))

        declaration = _as_declaration(node, lines, start, end, layer=layer, notes=notes)
        if declaration is not None:
            declarations.append(declaration)
            continue
        raw_unplaced.append((start, end, _unplaceable_reason(node)))

    unplaced = _merge_unplaced(raw_unplaced, lines)
    merged = [_Accounted(block.start_line, block.end_line) for block in unplaced]
    return declarations, unplaced, _gap_notes(lines, claimed + merged)


def _statement_start(node: ast.stmt) -> int:
    """First source line of *node*, decorators included."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        for decorator in node.decorator_list:
            return min(node.lineno, decorator.lineno)
    return node.lineno


def _attach_comment_block(lines: list[str], start: int, claimed: list[_Accounted]) -> int:
    """Walk up from *start* over comment-only lines sitting directly above it."""
    taken = max((item.end for item in claimed if item.end < start), default=0)
    line = start
    while line - 1 > taken:
        candidate = lines[line - 2].strip()
        if not candidate.startswith("#"):
            break
        line -= 1
    return line


def _as_declaration(
    node: ast.stmt,
    lines: list[str],
    start: int,
    end: int,
    *,
    layer: str | None,
    notes: list[str],
) -> DraftDeclaration | None:
    """Build a declaration for *node*, or ``None`` when it cannot be placed."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        form = "helper" if node.name.startswith("_") else "nerve"
        lifted = _lift_registration(node, notes)
        return DraftDeclaration(
            name=node.name,
            form=form,
            kind=None,
            intent=lifted.intent,
            layer=lifted.layer if layer is None else layer,
            fields=lifted.fields,
            body=_body_text(lines, start, end, lifted.drop_lines),
            start_line=start,
            end_line=end,
        )

    if isinstance(node, ast.ClassDef):
        lifted = _lift_registration(node, notes)
        kind = lifted.kind or _class_kind(node)
        if lifted.kind is None and kind == "MODEL" and not _has_model_shape(node):
            notes.append(
                f"`{node.name}` is a plain class, so the draft calls it a cell of kind "
                "MODEL. If it is really a service or an adapter over something outside "
                "the program, make it a nerve of kind SERVICE or ADAPTER instead."
            )
        return DraftDeclaration(
            name=node.name,
            form="cell",
            kind=kind,
            intent=lifted.intent,
            layer=lifted.layer if layer is None else layer,
            fields=lifted.fields,
            body=_body_text(lines, start, end, lifted.drop_lines),
            start_line=start,
            end_line=end,
        )

    constant = _constant_name(node)
    if constant is not None:
        return DraftDeclaration(
            name=constant,
            form="cell",
            kind="CONSTANT",
            intent=None,
            layer=layer,
            fields=(),
            body=_body_text(lines, start, end, frozenset()),
            start_line=start,
            end_line=end,
        )

    return None


def _body_text(lines: list[str], start: int, end: int, drop: frozenset[int]) -> str:
    """The verbatim source of ``[start, end]``, minus any dropped lines."""
    kept = [
        lines[number - 1] for number in range(start, end + 1) if number not in drop
    ]
    return "".join(kept)


def _constant_name(node: ast.stmt) -> str | None:
    """The upper-case constant this assignment declares, if it is one."""
    if isinstance(node, ast.AnnAssign):
        annotated = node.target
        if isinstance(annotated, ast.Name) and _is_constant_name(annotated.id):
            return annotated.id
        return None
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        assigned = node.targets[0]
        if isinstance(assigned, ast.Name) and _is_constant_name(assigned.id):
            return assigned.id
    return None


def _is_constant_name(name: str) -> bool:
    """Whether *name* reads as a constant: upper-case, not a dunder."""
    if name.startswith("__"):
        return False
    return name.isupper() and any(char.isalpha() for char in name)


def _class_kind(node: ast.ClassDef) -> str:
    """The cell kind this class's shape points at — a hint, never a decision."""
    bases = [_expression_name(base) for base in node.bases]
    tails = [base.rpartition(".")[2] for base in bases]
    decorators = [_expression_name(item) for item in node.decorator_list]
    decorator_tails = [item.rpartition(".")[2].partition("(")[0] for item in decorators]

    if any(tail.endswith(("Error", "Exception")) or tail == "BaseException" for tail in tails):
        return "EXCEPTION"
    if any(tail in {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"} for tail in tails):
        return "ENUM"
    if any(tail == "Protocol" for tail in tails):
        return "TYPE"
    if any(tail in {"NamedTuple", "TypedDict"} for tail in tails):
        return "MODEL"
    if any(tail == "BaseModel" for tail in tails):
        return "MODEL"
    if any(tail == "dataclass" for tail in decorator_tails):
        return "MODEL"
    return "MODEL"


def _has_model_shape(node: ast.ClassDef) -> bool:
    """Whether the class's own shape said MODEL, rather than the fallback."""
    bases = [_expression_name(base).rpartition(".")[2] for base in node.bases]
    decorators = [
        _expression_name(item).rpartition(".")[2].partition("(")[0]
        for item in node.decorator_list
    ]
    if any(base in {"NamedTuple", "TypedDict", "BaseModel"} for base in bases):
        return True
    return "dataclass" in decorators


def _unplaceable_reason(node: ast.stmt) -> str:
    """One plain sentence saying why *node* has no declaration form."""
    if isinstance(node, ast.If):
        if _is_main_guard(node):
            return (
                "the `if __name__` guard that runs this file as a script; a s0ma "
                "project names its entry points in [tool.s0ma] bootstrap_files instead"
            )
        if _is_type_checking_guard(node):
            blocker = _type_checking_promotion(node)[1]
            return (
                f"imports guarded by TYPE_CHECKING, kept here because {blocker}; s0ma "
                "declares imports in the module header and they always run, so check "
                "for an import cycle before moving these to requires: or uses:"
            )
        return "a top-level `if` statement, which runs when the module is imported"
    if isinstance(node, ast.Try):
        return "a top-level `try` block, which runs when the module is imported"
    if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
        return "a top-level loop, which runs when the module is imported"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "a top-level `with` block, which runs when the module is imported"
    if isinstance(node, ast.Match):
        return "a top-level `match` statement, which runs when the module is imported"
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return (
            "a module-level assignment that is not an upper-case constant; a value "
            "worked out while the module is being imported has no declaration form"
        )
    if isinstance(node, ast.Expr):
        return "a top-level statement that does something when the module is imported"
    return f"a top-level `{type(node).__name__.lower()}` statement with no declaration form"


def _is_main_guard(node: ast.If) -> bool:
    """Whether this ``if`` is the ``__name__ == "__main__"`` guard."""
    test = node.test
    if not isinstance(test, ast.Compare) or not isinstance(test.left, ast.Name):
        return False
    return test.left.id == "__name__"


def _is_type_checking_guard(node: ast.If) -> bool:
    """Whether this ``if`` is guarded by ``TYPE_CHECKING``."""
    return _TYPE_CHECKING in _expression_name(node.test)


def _is_plain_type_checking_test(test: ast.expr) -> bool:
    """Whether *test* is exactly ``TYPE_CHECKING`` or ``<dotted>.TYPE_CHECKING``.

    Narrower than :func:`_is_type_checking_guard` on purpose, and only
    for promotion: that one matches any test mentioning the name, so it
    also catches ``if not TYPE_CHECKING:`` — a runtime-only fallback
    whose imports must keep running at runtime and nowhere else.
    """
    if isinstance(test, ast.Name):
        return test.id == _TYPE_CHECKING
    if isinstance(test, ast.Attribute):
        return test.attr == _TYPE_CHECKING and isinstance(test.value, (ast.Name, ast.Attribute))
    return False


def _type_checking_promotion(
    node: ast.If,
) -> tuple[tuple[ast.Import | ast.ImportFrom, ...], str | None]:
    """Whether this ``TYPE_CHECKING`` block's imports can join the header.

    Returns the block's import statements and ``None`` when every one of
    them names a standard-library module, so the block is a header fact
    (D1b — see the module docstring for the four conditions and why they
    are the safe ones). Otherwise returns no imports and one phrase
    naming the first thing that stopped it, which the un-placeable
    block's reason then quotes so the person deciding knows what to look
    at.

    This is the single place the rule lives: the harvester and
    :func:`account_lines` both ask it, so the draft and its audit cannot
    disagree about who owns the block's lines.
    """
    if not _is_plain_type_checking_test(node.test):
        return (), "its test is more than a plain TYPE_CHECKING check"
    if node.orelse:
        return (), "it has an `else:` branch, which runs when the module is imported"
    imports: list[ast.Import | ast.ImportFrom] = []
    for statement in node.body:
        if not isinstance(statement, (ast.Import, ast.ImportFrom)):
            return (), "it holds a statement that is not an import"
        blocker = _non_stdlib_import(statement)
        if blocker is not None:
            return (), blocker
        imports.append(statement)
    return tuple(imports), None


def _non_stdlib_import(node: ast.Import | ast.ImportFrom) -> str | None:
    """Name the first module this import reaches that is not standard library.

    A relative import is first-party by definition, whatever it reaches,
    so it is reported without resolving it. Everything else is decided
    by its first dotted segment against :data:`sys.stdlib_module_names`,
    the same frozenset ``adopt/graph.py`` classifies with, so a draft
    reads identically on macOS, Linux and Windows. The decision is taken
    on that first segment; the phrase names the module as it is written,
    which is what the person has to go and look at.
    """
    if isinstance(node, ast.ImportFrom):
        if node.level:
            spelled = "." * node.level + (node.module or "")
            return f"`{spelled}` is a relative import, so it reaches another module of this project"
        return _stdlib_refusal(node.module or "")
    for alias in node.names:
        refusal = _stdlib_refusal(alias.name)
        if refusal is not None:
            return refusal
    return None


def _stdlib_refusal(module: str) -> str | None:
    """One phrase when *module* is not standard library, else ``None``."""
    if module.partition(".")[0] in sys.stdlib_module_names:
        return None
    return f"`{module}` is not part of Python's standard library"


def _is_promoted_guard(node: ast.stmt) -> bool:
    """Whether *node* is a ``TYPE_CHECKING`` block the header absorbed."""
    if not isinstance(node, ast.If) or not _is_type_checking_guard(node):
        return False
    return _type_checking_promotion(node)[1] is None


def _promotion_note(start: int, end: int) -> str:
    """The one sentence a promoted ``TYPE_CHECKING`` block leaves behind."""
    span = f"line {start}" if start == end else f"lines {start}-{end}"
    return (
        f"The imports under `if TYPE_CHECKING:` on {span} come only from Python's standard "
        "library, so they were moved into the module header's requires: list; importing "
        "them when the module loads costs nothing and cannot create an import cycle."
    )


def _merge_unplaced(raw: list[tuple[int, int, str]], lines: list[str]) -> list[DraftUnplaced]:
    """Merge neighbouring unplaced statements into one block each.

    Two unplaced statements with nothing but blank or comment lines
    between them become one carrier, so a person moving the code sees it
    the way it was written instead of in slices.
    """
    blocks: list[DraftUnplaced] = []
    for start, end, reason in sorted(raw, key=lambda item: item[0]):
        if blocks and _only_gap_between(lines, blocks[-1].end_line, start):
            previous = blocks[-1]
            merged_reason = (
                previous.reason
                if reason in previous.reason
                else f"{previous.reason}; and {reason}"
            )
            blocks[-1] = DraftUnplaced(
                text=_body_text(lines, previous.start_line, end, frozenset()),
                start_line=previous.start_line,
                end_line=end,
                reason=merged_reason,
            )
            continue
        blocks.append(
            DraftUnplaced(
                text=_body_text(lines, start, end, frozenset()),
                start_line=start,
                end_line=end,
                reason=reason,
            )
        )
    return blocks


def _only_gap_between(lines: list[str], previous_end: int, start: int) -> bool:
    """Whether every line between two ranges is blank or comment-only."""
    return all(
        _is_gap_line(lines[number - 1]) for number in range(previous_end + 1, start)
    )


def _is_gap_line(line: str) -> bool:
    """Whether *line* is blank or holds nothing but a comment."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _gap_notes(lines: list[str], claimed: list[_Accounted]) -> list[str]:
    """Notes for comment blocks that ended up attached to nothing."""
    owned: set[int] = set()
    for item in claimed:
        owned.update(range(item.start, item.end + 1))

    notes: list[str] = []
    run: list[int] = []
    for number in range(1, len(lines) + 1):
        if number in owned or not lines[number - 1].strip().startswith("#"):
            if run:
                notes.append(_gap_note(run))
                run = []
            continue
        run.append(number)
    if run:
        notes.append(_gap_note(run))
    return notes


def _gap_note(run: list[int]) -> str:
    """One note naming a comment block the draft does not carry.

    The whole sentence agrees in number, not just the noun: a single
    line "holds" and "sits" and is not carried, where several "hold" and
    "sit" and are not (pilot defect G2-15 — three of these appeared in
    one draft, each reading "Line 58 … hold … they").
    """
    one = len(run) == 1
    span = f"Line {run[0]}" if one else f"Lines {run[0]}-{run[-1]}"
    holds = "holds" if one else "hold"
    sits = "sits" if one else "sit"
    they = "it is" if one else "they are"
    read = "Read it" if one else "Read them"
    return (
        f"{span} of the Python file {holds} only comments and {sits} above nothing the "
        f"draft declares, so {they} not carried into it. {read} before you delete "
        f"the file."
    )


# ---------------------------------------------------------------------------
# Lifting a registered @component (rung 2 carry-forward)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Lifted:
    """What a s0ma registration decorator gave us, if there was one."""

    intent: str | None
    layer: str | None
    kind: str | None
    fields: tuple[tuple[str, str], ...]
    drop_lines: frozenset[int]


_EMPTY_LIFT = _Lifted(intent=None, layer=None, kind=None, fields=(), drop_lines=frozenset())

_CONTRACT_FIELDS = {
    "preconditions": "expects",
    "postconditions": "guarantees",
    "forbids": "forbids",
    "invariants": "invariants",
    "max_latency_ms": "latency_ms",
}

_LIFTED_ARGUMENTS = frozenset({"name", "kind", "layer", "intent", "version", "contracts"})
"""``@component`` arguments the draft has a home for; the rest get a note."""


def _lift_registration(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, notes: list[str]
) -> _Lifted:
    """Lift an existing ``@component`` / ``@internal`` into draft fields.

    Those intents were written by a person and are real: they are carried
    over verbatim and never replaced by a placeholder. The decorator
    itself is dropped from the body, because its content has moved into
    the declaration header.
    """
    for decorator in node.decorator_list:
        name = _expression_name(decorator).partition("(")[0].rpartition(".")[2]
        if name == "internal":
            return _Lifted(
                intent=None,
                layer=None,
                kind=None,
                fields=(("visibility", "INTERNAL"),),
                drop_lines=_decorator_lines(decorator),
            )
        if name != "component" or not isinstance(decorator, ast.Call):
            continue
        return _lift_component(decorator, node, notes)
    return _EMPTY_LIFT


def _lift_component(
    call: ast.Call,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    notes: list[str],
) -> _Lifted:
    """Read one ``@component(...)`` call into the draft's header fields."""
    positional = ["name", "kind", "layer", "intent"]
    arguments: dict[str, ast.expr] = {}
    for index, value in enumerate(call.args):
        if index < len(positional):
            arguments[positional[index]] = value
    for keyword in call.keywords:
        if keyword.arg is not None:
            arguments[keyword.arg] = keyword.value

    fields: list[tuple[str, str]] = []
    intent = _string_value(arguments.get("intent"))
    layer = _enum_tail(arguments.get("layer"))
    kind = _enum_tail(arguments.get("kind"))
    registered_name = _string_value(arguments.get("name"))
    if registered_name is not None and registered_name != node.name:
        notes.append(
            f"`{node.name}` was registered under the name {registered_name}. The draft "
            f"declares it as {node.name}, because a declaration's name is the name its "
            "body defines."
        )
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and kind is not None:
        fields.append(("kind", kind))
        kind = None

    version = _string_value(arguments.get("version"))
    if version is not None:
        fields.append(("version", version))

    contracts = arguments.get("contracts")
    if isinstance(contracts, ast.Call):
        fields.extend(_lift_contract(contracts))

    for unhandled in sorted(set(arguments) - _LIFTED_ARGUMENTS):
        notes.append(
            f"`{node.name}`'s registration also carried {unhandled}=..., which has no "
            "field on a declaration. Read it in the Python file before you delete it."
        )

    return _Lifted(
        intent=intent,
        layer=layer,
        kind=kind,
        fields=tuple(fields),
        drop_lines=_decorator_lines(call),
    )


def _lift_contract(call: ast.Call) -> list[tuple[str, str]]:
    """Map a core ``Contract(...)`` onto the declaration's contract fields."""
    fields: list[tuple[str, str]] = []
    for keyword in call.keywords:
        if keyword.arg is None or keyword.arg not in _CONTRACT_FIELDS:
            continue
        target = _CONTRACT_FIELDS[keyword.arg]
        value = keyword.value
        if isinstance(value, (ast.List, ast.Tuple)):
            parts = [
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            if parts:
                fields.append((target, "; ".join(parts)))
            continue
        text = _string_value(value)
        if text is not None:
            fields.append((target, text))
        elif isinstance(value, ast.Constant) and isinstance(value.value, (int, float)):
            fields.append((target, str(value.value)))
    return fields


def _decorator_lines(node: ast.expr) -> frozenset[int]:
    """Every source line the decorator occupies, its ``@`` included.

    A decorator expression's first line *is* its ``@`` line: ``@`` and
    the expression that follows it cannot be split across lines.
    """
    return frozenset(range(node.lineno, _end_line(node) + 1))


def _string_value(node: ast.expr | None) -> str | None:
    """The value of a plain string literal, or ``None`` for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _enum_tail(node: ast.expr | None) -> str | None:
    """``Layer.DOMAIN`` → ``"DOMAIN"``; anything unrecognised → ``None``."""
    if node is None:
        return None
    if isinstance(node, ast.Attribute):
        return node.attr
    return _string_value(node)


def _expression_name(node: ast.expr) -> str:
    """A dotted, printable name for *node* — best effort, never raises."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_expression_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _expression_name(node.func)
    if isinstance(node, ast.Subscript):
        return _expression_name(node.value)
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - ast.unparse is total for real trees
        return ""


# ---------------------------------------------------------------------------
# References, for deciding which imports the header needs
# ---------------------------------------------------------------------------


def _referenced_names(
    declarations: list[DraftDeclaration], unplaced: list[DraftUnplaced]
) -> frozenset[str]:
    """Every root name the draft's bodies and unplaced blocks mention.

    An unplaced block counts: its text is going to become a body, and an
    import the header dropped would be lost by the time it does.
    """
    names: set[str] = set()
    for text in [declaration.body for declaration in declarations] + [
        block.text for block in unplaced
    ]:
        try:
            tree = ast.parse(_dedent(text))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(_expression_name(node).split(".")[0])
    return frozenset(names)


def _dedent(text: str) -> str:
    """Strip the first meaningful line's indent from every line of *text*."""
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            break
    else:
        return text
    if indent == 0:
        return text
    prefix = " " * indent
    return "\n".join(
        line[indent:] if line.startswith(prefix) else line for line in text.split("\n")
    )


def _end_line(node: ast.stmt | ast.expr) -> int:
    """The last source line of *node*, falling back to its first."""
    end = getattr(node, "end_lineno", None)
    return node.lineno if end is None else end


# ---------------------------------------------------------------------------
# The accounting proof
# ---------------------------------------------------------------------------


def account_lines(draft: DraftModule, source_text: str) -> tuple[str, ...]:
    """Say who owns every line of the harvested file — the "nothing is lost" proof.

    Returns one label per physical line of *source_text*, in order, so
    line *n* of the file is ``result[n - 1]``. The labels are:

    * ``"declaration:<name>"`` — inside that declaration's line range;
    * ``"unplaced:<start>-<end>"`` — inside that unplaced block;
    * ``"header:docstring"``, ``"header:import"``, ``"header:exports"`` —
      consumed as a header fact. A standard-library-only ``if
      TYPE_CHECKING:`` block is ``"header:import"`` too: its imports
      were promoted into ``requires:`` (D1b), so the block's lines
      belong to the header rather than to an un-placeable block;
    * ``"gap"`` — blank, or a comment that no declaration absorbed;
    * ``"unaccounted"`` — nothing claimed it, which is always a bug;
    * ``"conflict:<first>|<second>"`` — two owners claimed it, which is
      also always a bug.

    The header facts are re-derived from *source_text* with :mod:`ast`
    rather than read back out of the draft, so this really is an audit
    and not a restatement of what the harvester decided.
    """
    lines = source_text.splitlines()
    owners = [LINE_UNACCOUNTED] * len(lines)

    def claim(start: int, end: int, owner: str) -> None:
        for number in range(start, end + 1):
            if not 1 <= number <= len(owners):
                continue
            current = owners[number - 1]
            if current == LINE_UNACCOUNTED:
                owners[number - 1] = owner
            elif not current.startswith(_CONFLICT_PREFIX):
                owners[number - 1] = f"{_CONFLICT_PREFIX}{current}|{owner}"

    for declaration in draft.declarations:
        claim(
            declaration.start_line,
            declaration.end_line,
            f"{_DECLARATION_PREFIX}{declaration.name}",
        )
    for block in draft.unplaced:
        claim(
            block.start_line,
            block.end_line,
            f"{_UNPLACED_PREFIX}{block.start_line}-{block.end_line}",
        )

    try:
        tree = ast.parse(source_text)
    except SyntaxError:  # pragma: no cover - harvest_module refuses these first
        return tuple(owners)

    docstring_range = _docstring_range(tree)
    if docstring_range is not None:
        claim(docstring_range[0], docstring_range[1], _LINE_DOCSTRING)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or _is_promoted_guard(node):
            claim(node.lineno, _end_line(node), _LINE_IMPORT)
    _, exports_ranges = _collect_dunder_all(tree)
    for start, end in exports_ranges:
        claim(start, end, _LINE_EXPORTS)

    for index, owner in enumerate(owners):
        if owner == LINE_UNACCOUNTED and _is_gap_line(lines[index]):
            owners[index] = LINE_GAP

    return tuple(owners)
