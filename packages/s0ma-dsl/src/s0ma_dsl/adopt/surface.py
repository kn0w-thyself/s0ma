"""A Python module's public surface, read from its syntax and never imported.

Why this exists
---------------

Converting an existing Python module into a s0ma module has to keep one
promise: whatever the module offered its callers before, it still offers
afterwards. This module reads that promise out of the file's syntax tree
— the public names, what each one looks like, and what it says about
itself — as a :class:`~s0ma_dsl.adopt.model.ModuleSurface`.
:mod:`s0ma_dsl.adopt.parity` captures one before the conversion and
compares it with the converted module's surface afterwards.

**Nothing here imports or executes the file** (retrofit rule R-1). Code
that is being retrofitted is by definition not yet under s0ma's care:
importing it in order to look at it would run whatever its top level
runs, and a check that an import side effect can fool is not proof of
anything. Everything below is :mod:`ast` over file text.

What counts as public
---------------------

* **Top-level names** — a name with no leading underscore, intersected
  with a literal ``__all__`` when the module declares one. A module that
  builds ``__all__`` dynamically (a non-literal value, a second
  assignment, a ``+=``) is read as if it declared none: the underscore
  rule then decides, which captures more names rather than fewer.
* **Class members** — for every public class, each member written
  directly in its body: public methods, public nested classes and public
  class-level attributes, recorded flat as ``"Class.member"``.
* **Dunder members** — only the two in :data:`SURFACE_DUNDER_MEMBERS`:
  ``__init__`` and ``__call__``. Both are part of how a class is *used*
  rather than how it is built — the first is the constructor every
  caller goes through, the second is what makes an instance callable —
  and both routinely change shape during a conversion. Every other
  dunder (``__repr__``, ``__eq__``, ``__enter__``, …) is left out: it is
  reached through syntax rather than by name, and widening the list
  later would make every baseline captured under the narrow rule report
  spurious "extra" findings, so the two names are part of the
  ``s0ma-adopt-baseline@1`` contract, not a preference.
* **One level deep** — a nested class is recorded as ``"Outer.Inner"``,
  because a nested class quietly disappearing is a real break, but its
  own members are not: the surface is flat, and ``"Outer.Inner.method"``
  is not a shape :class:`~s0ma_dsl.adopt.model.SurfaceEntry` describes.
* **Written directly** — only statements in the module body and in a
  class body are read. A definition inside ``if``, ``try`` or a loop is
  conditional, not a promise, and is skipped. A name defined twice keeps
  the last definition, as the interpreter does; that is also what makes
  a ``@property`` / ``@x.setter`` pair record its setter.
* Imported names are never entries — an entry describes something the
  module *defines*. A re-export still shows up in ``dunder_all``.

What "normalised" means
-----------------------

Two files that differ only in blank lines, comments, import order,
string-quote style, trailing commas, or where a long signature was
wrapped must produce **equal** surfaces, or every parity check would
drown in cosmetic findings. :func:`ast.unparse` does most of that work:
it renders one canonical form for signatures, decorators, bases and
literal values (quotes become single quotes, adjacent string literals
fold, wrapping and comments are gone). Docstrings go through
:func:`inspect.cleandoc`, so how far a docstring was indented does not
change it.

Verified deterministic on CPython 3.11, 3.12 and 3.13 (the supported
range): the same source gives byte-identical unparse and docstring
output on all three. That matters twice over — a baseline is captured
once and compared long afterwards, possibly on another interpreter, and
the selfhost friction log's F-M3-8 records how raw ``__doc__`` differs
between those very versions. Reading docstrings from the syntax tree and
cleaning them sidesteps it; F-M2-5 (``from __future__ import
annotations`` changing ``inspect.signature`` output) cannot reach a
reader that never imports anything.

What is deliberately *not* normalised: a value that is computed rather
than written out. It is recorded as :data:`SURFACE_NON_LITERAL`, because
claiming to know statically what ``TIMEOUT = _read_config()`` equals
would be a lie.

Declared types
--------------

A name written with a type — ``title: str``, ``copies: int = 1``,
``DEFAULTS: Final[dict[str, int]] = {}`` — records that type, unparsed,
as the entry's ``annotation``. It has to be on the surface in its own
right: a dataclass field changing from ``str`` to ``int`` is the
commonest change a conversion makes, it changes nothing else about the
entry, and without an ``annotation`` it would pass a parity check in
silence.

The type is recorded **as declared, not as resolved**. A quoted forward
reference stays quoted (``author: "Person"`` records ``"'Person'"``),
and ``from __future__ import annotations`` makes no difference, because
a reader that never imports the module has no way to resolve either and
should not pretend otherwise. Comparison is therefore textual: renaming
a type alias reads as a change, which is the safe direction to be wrong
in.

A name declared with a type but no value (``due: date``) is an entry
like any other, with ``value`` ``None`` — at class level it is a
dataclass field and plainly part of the shape, and at module level it is
kept for the same reason the reader keeps a class's, so that one rule
covers both. ``count = 0`` with no declared type records ``annotation``
``None``; so does every function, method and class, whose types live in
``signature`` and ``bases``.

Consumers: :mod:`s0ma_dsl.adopt.parity` (capture and compare) and the
``s0ma adopt baseline`` / ``s0ma adopt verify-parity`` commands.
"""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.model import ModuleSurface, SurfaceEntry

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "SURFACE_DUNDER_MEMBERS",
    "SURFACE_NON_LITERAL",
    "SurfaceReadError",
    "static_surface",
    "surface_from_source",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SURFACE_NON_LITERAL = "<non-literal>"
"""Recorded as a constant's or attribute's value when it is computed.

``MAX = 10`` is written out and comparable; ``MAX = _from_env()`` is
not. Rather than pretend, the surface records this marker: two computed
values are never reported as equal *or* as changed on their text alone.

Defined once, here, and imported by the comparer — part of the
``s0ma-adopt-baseline@1`` contract, so changing the spelling would
invalidate every captured baseline.
"""

SURFACE_DUNDER_MEMBERS = ("__call__", "__init__")
"""The only dunder members that are part of a class's captured surface.

Sorted, so the tuple reads the same way it is tested. See the module
docstring for why these two and not the rest, and why widening the list
is a contract change rather than a tweak.
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SurfaceReadError(Exception):
    """Raised when a file's public surface cannot be read at all.

    Unreadable, not-UTF-8, or not valid Python. Every message says what
    happened and what the person can do about it; callers can print one
    straight out.
    """


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def static_surface(path: Path, *, module: str | None = None) -> ModuleSurface:
    """Read the public surface of the Python file at *path*.

    The file is read as UTF-8 text and parsed; it is never imported and
    never executed.

    *module* is the dotted module name to record in the surface. Callers
    that know it — the baseline store does, from discovery — pass it.
    Left out, it falls back to what the filename alone can say (the
    package name for an ``__init__.py``, otherwise the stem), which is
    enough for a one-off read and never enough for a record.

    Raises :class:`SurfaceReadError` when the file cannot be read or is
    not valid Python.
    """
    origin = path.as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SurfaceReadError(
            f"There is no file at {origin}, so its public surface cannot be read. "
            f"Check the path, or recover the file from version control, then try again."
        ) from exc
    except UnicodeDecodeError as exc:
        raise SurfaceReadError(
            f"The file {origin} is not UTF-8 text, so its public surface cannot be "
            f"read. Re-save it as UTF-8 and try again."
        ) from exc
    except OSError as exc:
        raise SurfaceReadError(
            f"The file {origin} could not be read ({exc.strerror or exc}), so its "
            f"public surface cannot be read. Check the file's permissions and try again."
        ) from exc
    return _surface(source, module=module or _module_name_for(path), origin=origin)


def surface_from_source(source: str, module: str) -> ModuleSurface:
    """Read the public surface of Python *source* text for *module*.

    The same reading as :func:`static_surface`, for text a caller already
    holds. Raises :class:`SurfaceReadError` when *source* is not valid
    Python; the message names *module*, since there is no file to name.
    """
    return _surface(source, module=module, origin=module)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _surface(source: str, *, module: str, origin: str) -> ModuleSurface:
    """Parse *source* and assemble the surface; *origin* names it in errors."""
    tree = _parse(source, origin=origin)
    dunder_all = _literal_dunder_all(tree)
    return ModuleSurface(
        module=module,
        entries=_module_entries(tree, dunder_all),
        dunder_all=dunder_all,
    )


def _parse(source: str, *, origin: str) -> ast.Module:
    """Parse *source*, turning both parse failures into one friendly refusal."""
    try:
        return ast.parse(source)
    except SyntaxError as exc:
        location = f" at line {exc.lineno}" if exc.lineno else ""
        raise SurfaceReadError(
            f"{origin} is not valid Python ({exc.msg}{location}), so its public "
            f"surface cannot be read. Fix the error, then try again."
        ) from exc
    except ValueError as exc:
        # Source with a null byte in it reaches here rather than as a
        # SyntaxError; the text is not really Python source at all.
        raise SurfaceReadError(
            f"{origin} cannot be read as Python source ({exc}). Check that the file "
            f"is Python text and not binary, then try again."
        ) from exc


def _module_name_for(path: Path) -> str:
    """The best module name a filename alone can offer."""
    return path.parent.name if path.name == "__init__.py" else path.stem


def _module_entries(
    tree: ast.Module, dunder_all: tuple[str, ...] | None,
) -> tuple[SurfaceEntry, ...]:
    """Every public entry in *tree*, de-duplicated by name and sorted.

    Sorting by name is what puts a class next to its own ``Class.member``
    entries — ``"."`` sorts before every letter and digit — and is what
    makes two captures of the same module byte-identical.
    """
    collected: dict[str, SurfaceEntry] = {}
    for statement in tree.body:
        entries = _statement_entries(statement, dunder_all)
        if isinstance(statement, ast.ClassDef) and statement.name in collected:
            # A class defined a second time replaces the first one whole:
            # drop the members the earlier definition contributed, or a
            # member it no longer has would linger on the surface.
            for stale in [
                name for name in collected if name.startswith(f"{statement.name}.")
            ]:
                del collected[stale]
        for entry in entries:
            collected[entry.name] = entry
    return tuple(sorted(collected.values(), key=lambda entry: entry.name))


def _statement_entries(
    statement: ast.stmt, dunder_all: tuple[str, ...] | None,
) -> tuple[SurfaceEntry, ...]:
    """The entries one top-level statement contributes (often none)."""
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
        if not _is_public_top_level(statement.name, dunder_all):
            return ()
        return (_callable_entry(statement, name=statement.name, top_level=True),)
    if isinstance(statement, ast.ClassDef):
        if not _is_public_top_level(statement.name, dunder_all):
            return ()
        return _class_entries(statement)
    if isinstance(statement, ast.Assign | ast.AnnAssign):
        return tuple(
            SurfaceEntry(
                name=name,
                category="constant",
                signature=None,
                annotation=annotation,
                decorators=(),
                bases=(),
                docstring=None,
                value=value,
            )
            for name, value, annotation in _assigned_values(statement)
            if _is_public_top_level(name, dunder_all)
        )
    return ()


def _class_entries(node: ast.ClassDef) -> tuple[SurfaceEntry, ...]:
    """The class itself, then every public member written in its body."""
    entries = [
        SurfaceEntry(
            name=node.name,
            category="class",
            signature=None,
            annotation=None,
            decorators=_unparsed(node.decorator_list),
            bases=_bases(node),
            docstring=_docstring(node),
            value=None,
        )
    ]
    for member in node.body:
        if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
            if not _is_public_member(member.name):
                continue
            entries.append(
                _callable_entry(
                    member, name=f"{node.name}.{member.name}", top_level=False,
                )
            )
        elif isinstance(member, ast.ClassDef):
            if not _is_public_member(member.name):
                continue
            entries.append(
                SurfaceEntry(
                    name=f"{node.name}.{member.name}",
                    category="class",
                    signature=None,
                    annotation=None,
                    decorators=_unparsed(member.decorator_list),
                    bases=_bases(member),
                    docstring=_docstring(member),
                    value=None,
                )
            )
        elif isinstance(member, ast.Assign | ast.AnnAssign):
            entries.extend(
                SurfaceEntry(
                    name=f"{node.name}.{name}",
                    category="attribute",
                    signature=None,
                    annotation=annotation,
                    decorators=(),
                    bases=(),
                    docstring=None,
                    value=value,
                )
                for name, value, annotation in _assigned_values(member)
                if _is_public_member(name)
            )
    return tuple(entries)


def _callable_entry(
    node: ast.FunctionDef | ast.AsyncFunctionDef, *, name: str, top_level: bool,
) -> SurfaceEntry:
    """One function or method entry.

    Sync and async are different categories on purpose: a function that
    stops being awaitable breaks every caller, so it must not compare
    equal to the function it replaced.
    """
    if isinstance(node, ast.AsyncFunctionDef):
        category = "async_function" if top_level else "async_method"
    else:
        category = "function" if top_level else "method"
    return SurfaceEntry(
        name=name,
        category=category,
        signature=_signature(node),
        # A callable's types are in its signature; annotation is for a
        # name declared with a type, and recording one here twice over
        # would make a single change read as two findings.
        annotation=None,
        decorators=_unparsed(node.decorator_list),
        bases=(),
        docstring=_docstring(node),
        value=None,
    )


# ---------------------------------------------------------------------------
# Normalising one piece at a time
# ---------------------------------------------------------------------------


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The parameter list and return annotation, canonically rendered.

    ``self`` and ``cls`` are kept — dropping one is a real change of
    calling convention — and defaults, annotations, ``/``, ``*``,
    ``*args`` and ``**kwargs`` all come through :func:`ast.unparse`, so
    wrapping, comments and quote style cannot show up as a difference.
    """
    arguments = ast.unparse(node.args)
    returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    return f"({arguments}){returns}"


def _unparsed(expressions: list[ast.expr]) -> tuple[str, ...]:
    """Render expressions (decorators) canonically, source order kept."""
    return tuple(ast.unparse(expression) for expression in expressions)


def _bases(node: ast.ClassDef) -> tuple[str, ...]:
    """Base classes, then class keywords, as written in the class header.

    ``metaclass=...`` and friends are included after the positional
    bases: changing the metaclass changes how every instance behaves, so
    it belongs on the surface rather than out of sight.
    """
    rendered = [ast.unparse(base) for base in node.bases]
    for keyword in node.keywords:
        value = ast.unparse(keyword.value)
        rendered.append(f"**{value}" if keyword.arg is None else f"{keyword.arg}={value}")
    return tuple(rendered)


def _docstring(node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The docstring after :func:`inspect.cleandoc`, or ``None``.

    Cleaning is not cosmetic. How deeply a docstring was indented is an
    accident of where it was written, and a converted module writes its
    bodies at a different depth; comparing raw text would report every
    moved definition as a documentation change.
    """
    raw = ast.get_docstring(node, clean=False)
    return None if raw is None else inspect.cleandoc(raw)


def _assigned_values(
    statement: ast.Assign | ast.AnnAssign,
) -> list[tuple[str, str | None, str | None]]:
    """``(name, recorded value, declared type)`` for each name one assignment binds.

    For the value, ``None`` means the name was declared without one
    (``count: int``); :data:`SURFACE_NON_LITERAL` means it has one but
    it is computed — including every name bound by unpacking, where no
    single written-out value belongs to any one of them.

    For the declared type, ``None`` means the assignment declared none.
    Only an annotated assignment can carry one, and only ever for the
    single name it binds: ``a = b = 0`` and ``a, b = pair`` cannot be
    annotated in Python at all, so both come back with ``None``.
    """
    if isinstance(statement, ast.AnnAssign):
        annotated = statement.target
        if not isinstance(annotated, ast.Name):
            return []
        return [
            (
                annotated.id,
                _literal_value(statement.value),
                ast.unparse(statement.annotation),
            )
        ]

    values: list[tuple[str, str | None, str | None]] = []
    for target in statement.targets:
        if isinstance(target, ast.Name):
            values.append((target.id, _literal_value(statement.value), None))
        elif isinstance(target, ast.Tuple | ast.List):
            values.extend(
                (element.id, SURFACE_NON_LITERAL, None)
                for element in target.elts
                if isinstance(element, ast.Name)
            )
    return values


def _literal_value(value: ast.expr | None) -> str | None:
    """The value as written when it is a literal, else the marker.

    "Literal" is :func:`ast.literal_eval`'s definition — numbers,
    strings, bytes, booleans, ``None``, ``...``, and tuples, lists, sets
    and dicts of those — which is exactly "written out rather than
    computed". Anything else (a call, a name, arithmetic, an f-string)
    is recorded as :data:`SURFACE_NON_LITERAL`.
    """
    if value is None:
        return None
    try:
        ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return SURFACE_NON_LITERAL
    return ast.unparse(value)


# ---------------------------------------------------------------------------
# Who is public
# ---------------------------------------------------------------------------


def _is_public_top_level(name: str, dunder_all: tuple[str, ...] | None) -> bool:
    """A top-level name with no leading underscore, and in ``__all__`` if declared."""
    if name.startswith("_"):
        return False
    return dunder_all is None or name in dunder_all


def _is_public_member(name: str) -> bool:
    """A class member with no leading underscore, plus the two sanctioned dunders."""
    return name in SURFACE_DUNDER_MEMBERS or not name.startswith("_")


def _literal_dunder_all(tree: ast.Module) -> tuple[str, ...] | None:
    """The module's ``__all__`` in declared order, or ``None``.

    ``None`` covers both "does not declare one" and "does not declare a
    plain literal one" — a computed value, a second assignment, or a
    ``__all__ += [...]`` — because a list nobody can read statically is
    not a promise this tool can record. Its declared order is kept: the
    record says what the module wrote, and the comparer is the one that
    ignores order.
    """
    found: tuple[str, ...] | None = None
    assignments = 0
    for statement in tree.body:
        if isinstance(statement, ast.AugAssign):
            target = statement.target
            if isinstance(target, ast.Name) and target.id == "__all__":
                return None
            continue
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        targets: list[ast.expr] = (
            [statement.target]
            if isinstance(statement, ast.AnnAssign)
            else list(statement.targets)
        )
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            continue
        assignments += 1
        if assignments > 1:
            return None
        found = _string_sequence(statement.value)
        if found is None:
            return None
    return found


def _string_sequence(value: ast.expr | None) -> tuple[str, ...] | None:
    """A written-out list or tuple of strings, or ``None`` if it is anything else."""
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    names: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.append(element.value)
    return tuple(names)
