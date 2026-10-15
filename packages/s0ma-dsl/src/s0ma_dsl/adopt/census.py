"""Census — everything one Python file tells a static reader.

:func:`census_file` opens one discovered file, parses it with
:mod:`ast`, and returns a :class:`~s0ma_dsl.adopt.model.ModuleCensus`:
what it defines, what it imports, how big it is, whether anything runs
at import time, and the hash of the bytes all of that was read from.

The three promises
------------------

* **Nothing is imported or executed** (retrofit rule R-1). Every fact
  below comes from the parse tree. That is why a "kind" here is a
  *hint*: a static reader can see that a class inherits ``Enum``, not
  what the class means.
* **Nothing is written** (retrofit rule R-2). No cache, no temporary
  file, nothing beside the sources. In particular
  :func:`s0ma_dsl.derived_surface.derive_python_surface` is *not*
  called: it writes a cache under ``.s0ma.cache/``, which would make a
  read-only scan leave a trace on a tree the user has not consented to
  change yet. Its private helpers are not reused either — they sort and
  de-duplicate ``__all__`` and flatten imports to bare dotted strings,
  and this census needs declared order and per-import facts (line,
  deferred, type-checking) that those helpers do not carry.
* **A bad file is a fact, never an exception.** A file that is not
  UTF-8, or that does not parse, comes back as a census with
  ``parse_error`` set and empty ``entities``/``imports``. A scan reads
  someone else's tree; it does not get to refuse over one broken file.

Where the definitions come from
-------------------------------

"Public" mirrors core's own rule — no leading underscore, defined in
this module — so the scan's numbers line up with what the runtime's
import hook would say about the same tree
(``s0ma/import_hook.py``'s ``_get_unregistered_entities``), narrowed by
a literal ``__all__`` when the module declares one. The one deliberate
widening is documented on :func:`_is_public`.

Consumers: ``adopt/graph.py`` (imports), ``adopt/proposals.py``
(entities and size), ``adopt/report.py`` (all of it) and
``adopt/harvest.py``.
"""

from __future__ import annotations

import ast
import sys
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.model import EntityFact, ImportFact, ModuleCensus
from s0ma_dsl.codegen.build_manifest import compute_file_hash

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from s0ma_dsl.adopt.model import SourceFile

__all__ = ["census_file"]


# Entity categories, fixed by ``model.EntityFact``.
_CATEGORY_FUNCTION = "function"
_CATEGORY_ASYNC_FUNCTION = "async_function"
_CATEGORY_CLASS = "class"
_CATEGORY_CONSTANT = "constant"

# Import origins, fixed by ``model.ImportFact``. The census sets only the
# two it can know without the whole tree in hand: ``stdlib`` (the
# interpreter says so) and ``unresolved`` (everything else). Telling
# first-party from third-party needs the full set of discovered modules,
# which is ``adopt/graph.py``'s job.
_ORIGIN_STDLIB = "stdlib"
_ORIGIN_UNRESOLVED = "unresolved"

# Shape-based kind hints. Plain words for what a definition *looks*
# like; mapping them onto the DSL's kind taxonomy is a later milestone's
# decision, not this one's.
_HINT_EXCEPTION = "EXCEPTION"
_HINT_ENUM = "ENUM"
_HINT_MODEL = "MODEL"
_HINT_PROTOCOL = "PROTOCOL"
_HINT_CONSTANT = "CONSTANT"
_HINT_FUNCTION = "FUNCTION"
_HINT_CLASS = "CLASS"

_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "ReprEnum"})
_MODEL_BASES = frozenset({"NamedTuple", "TypedDict", "BaseModel"})
_MODEL_DECORATORS = frozenset({"dataclass"})
_PROTOCOL_BASES = frozenset({"Protocol"})

# Decorator names that mean "this definition is already registered with
# s0ma" — rung 2 of the ladder, registered in place. Matched on the
# decorator's root name, so ``@component(...)``, ``@s0ma.component(...)``
# and a bare ``@internal`` all count. A project with its own unrelated
# decorator named ``component`` would read as registered; that is a hint
# in a report, and the harvester re-reads the decorator itself before
# lifting anything from it.
_REGISTRATION_DECORATORS = frozenset({"component", "internal"})

_TYPE_CHECKING_NAME = "TYPE_CHECKING"


def census_file(root: Path, source: SourceFile) -> ModuleCensus:
    """Return everything *source* tells a static reader, read from *root*.

    *source* is a record from :func:`~s0ma_dsl.adopt.discovery.discover_sources`;
    its ``path`` is project-relative and POSIX, and is resolved against
    *root* here. The returned census always carries ``lines``, ``sloc``
    and ``content_hash`` — they are true even of a file that does not
    parse — and carries ``parse_error`` instead of entities and imports
    when the file could not be read as Python.
    """
    path = root / source.path
    text, read_error = _read_source(path)

    if text is None:
        return _empty_census(source, parse_error=read_error, content_hash=_hash_bytes(path))

    lines, sloc = _measure(text)
    content_hash = compute_file_hash(text)

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return ModuleCensus(
            source=source,
            lines=lines,
            sloc=sloc,
            entities=(),
            imports=(),
            dunder_all=None,
            has_main_guard=False,
            top_level_effects=0,
            parse_error=_syntax_error_sentence(exc),
            content_hash=content_hash,
        )

    dunder_all = _literal_dunder_all(tree)
    return ModuleCensus(
        source=source,
        lines=lines,
        sloc=sloc,
        entities=_collect_entities(tree, dunder_all),
        imports=_collect_imports(tree, _package_of(source)),
        dunder_all=dunder_all,
        has_main_guard=_has_main_guard(tree),
        top_level_effects=_count_top_level_effects(tree),
        parse_error=None,
        content_hash=content_hash,
    )


# ---------------------------------------------------------------------------
# Reading and measuring
# ---------------------------------------------------------------------------


def _read_source(path: Path) -> tuple[str | None, str]:
    """Return *path*'s UTF-8 text, or ``None`` and a plain-language reason.

    Strict decoding, deliberately: a file silently mangled into
    something that parses would produce a census full of quiet fiction.
    """
    try:
        return path.read_text(encoding="utf-8"), ""
    except UnicodeDecodeError:
        return None, (
            "This file is not UTF-8 text, so it cannot be read as Python source. "
            "Convert it to UTF-8, or leave it out of the conversion."
        )
    except OSError:
        return None, (
            "This file could not be opened for reading. Check that it still "
            "exists and that you have permission to read it."
        )


def _hash_bytes(path: Path) -> str:
    """Return ``sha256:<hex>`` over *path*'s raw bytes, for an unreadable file.

    The readable path hashes text, matching
    :func:`s0ma_dsl.adoption.compute_adopted_hash`. When the text cannot
    be decoded there is no text to hash, so the bytes stand in — still a
    true content hash of the file, and always accompanied by a
    ``parse_error`` that says the census is degraded. A file that cannot
    be opened at all hashes as empty; nothing reads a hash whose census
    already says the file could not be read.
    """
    try:
        return compute_file_hash(path.read_bytes())
    except OSError:
        return compute_file_hash(b"")


def _measure(text: str) -> tuple[int, int]:
    """Return ``(lines, sloc)``: physical lines, and lines that carry code.

    ``sloc`` counts every line that is neither blank nor a comment. It is
    the cheap, conventional definition and it has the cheap, conventional
    blind spot: a line inside a triple-quoted string that begins with
    ``#`` is counted as a comment. That costs a handful of lines on a
    docstring-heavy module and never changes which effort band it lands
    in, which is all ``sloc`` is used for.
    """
    physical = text.splitlines()
    code = 0
    for line in physical:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            code += 1
    return len(physical), code


def _empty_census(source: SourceFile, *, parse_error: str, content_hash: str) -> ModuleCensus:
    """Return the census of a file that could not be read at all."""
    return ModuleCensus(
        source=source,
        lines=0,
        sloc=0,
        entities=(),
        imports=(),
        dunder_all=None,
        has_main_guard=False,
        top_level_effects=0,
        parse_error=parse_error,
        content_hash=content_hash,
    )


def _syntax_error_sentence(exc: SyntaxError | ValueError) -> str:
    """Return one plain sentence naming where the file stopped parsing."""
    line = getattr(exc, "lineno", None)
    detail = getattr(exc, "msg", None) or "the file is not valid Python"
    where = f" at line {line}" if isinstance(line, int) else ""
    return (
        f"This file is not valid Python{where} ({detail}), so nothing inside it "
        f"could be read. Fix the file, then run the scan again."
    )


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def _collect_entities(
    tree: ast.Module, dunder_all: tuple[str, ...] | None
) -> tuple[EntityFact, ...]:
    """Return every top-level definition, in source order."""
    entities: list[EntityFact] = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entities.append(_function_fact(statement, dunder_all))
        elif isinstance(statement, ast.ClassDef):
            entities.append(_class_fact(statement, dunder_all))
        else:
            entities.extend(_constant_facts(statement, dunder_all))
    return tuple(entities)


def _function_fact(
    node: ast.FunctionDef | ast.AsyncFunctionDef, dunder_all: tuple[str, ...] | None
) -> EntityFact:
    """Return the fact for one top-level ``def`` or ``async def``."""
    decorators = _unparse_all(node.decorator_list)
    return EntityFact(
        name=node.name,
        category=(
            _CATEGORY_ASYNC_FUNCTION
            if isinstance(node, ast.AsyncFunctionDef)
            else _CATEGORY_FUNCTION
        ),
        line=node.lineno,
        public=_is_public(node.name, dunder_all),
        kind_hint=_HINT_FUNCTION,
        decorators=decorators,
        bases=(),
        has_docstring=ast.get_docstring(node) is not None,
        registered=_is_registered(node.decorator_list),
    )


def _class_fact(node: ast.ClassDef, dunder_all: tuple[str, ...] | None) -> EntityFact:
    """Return the fact for one top-level ``class``.

    ``bases`` carries the positional base expressions only. Keyword
    arguments in the class header (``metaclass=``, ``total=False``) are
    configuration, not ancestry, and putting them in a list called
    "bases" would make every later reader check.
    """
    return EntityFact(
        name=node.name,
        category=_CATEGORY_CLASS,
        line=node.lineno,
        public=_is_public(node.name, dunder_all),
        kind_hint=_class_kind_hint(node),
        decorators=_unparse_all(node.decorator_list),
        bases=_unparse_all(node.bases),
        has_docstring=ast.get_docstring(node) is not None,
        registered=_is_registered(node.decorator_list),
    )


def _constant_facts(
    statement: ast.stmt, dunder_all: tuple[str, ...] | None
) -> list[EntityFact]:
    """Return facts for the upper-case names *statement* assigns, if any.

    A constant is an assignment to an ``UPPER_CASE`` name — the Python
    convention, and the only signal a static reader has.  ``__all__`` is
    excluded: it is the module's export list, not one of its entities.

    An annotation with no value (``PENDING: int``) declares a name
    without binding one: at runtime the module has no such attribute, so
    the import hook would not see it and a draft has no value to carry
    into a CONSTANT declaration. It is a type statement, not an entity.
    """
    if isinstance(statement, ast.AnnAssign):
        if statement.value is None:
            return []
        targets: list[ast.expr] = [statement.target]
    elif isinstance(statement, ast.Assign):
        targets = list(statement.targets)
    else:
        return []

    facts: list[EntityFact] = []
    for name in _assigned_names(targets):
        if name == "__all__" or not name.isupper():
            continue
        facts.append(
            EntityFact(
                name=name,
                category=_CATEGORY_CONSTANT,
                line=statement.lineno,
                public=_is_public(name, dunder_all),
                kind_hint=_HINT_CONSTANT,
                decorators=(),
                bases=(),
                has_docstring=False,
                registered=False,
            )
        )
    return facts


def _assigned_names(targets: Iterable[ast.expr]) -> list[str]:
    """Return the plain names *targets* binds, including tuple unpacking."""
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(_assigned_names(target.elts))
    return names


def _is_public(name: str, dunder_all: tuple[str, ...] | None) -> bool:
    """Return ``True`` when *name* is on the module's public surface.

    Core's runtime rule, mirrored: no leading underscore, and defined in
    this module (true by construction here — the census only ever reads
    one file's own top level). When the module declares a literal
    ``__all__``, that list narrows the answer further, because a module
    with an ``__all__`` has stated its surface explicitly.

    One deliberate widening over core: core's import hook enforces
    registration on classes and functions only, so it never calls a
    module-level constant public. This census does, because the
    conversion needs to know which constants a module exports — a public
    ``MAX_LOANS`` becomes a declared CONSTANT in the draft, and dropping
    it from the public set would quietly drop it from the module's
    ``exports:`` too.
    """
    if name.startswith("_"):
        return False
    if dunder_all is not None:
        return name in dunder_all
    return True


def _class_kind_hint(node: ast.ClassDef) -> str:
    """Return the shape-based kind hint for a class, most specific first."""
    bases = {_root_name(base) for base in node.bases}
    decorators = {_decorator_root(decorator) for decorator in node.decorator_list}
    if any(base.endswith(("Error", "Exception")) or base == "BaseException" for base in bases):
        return _HINT_EXCEPTION
    if bases & _ENUM_BASES:
        return _HINT_ENUM
    if bases & _MODEL_BASES or decorators & _MODEL_DECORATORS:
        return _HINT_MODEL
    if bases & _PROTOCOL_BASES:
        return _HINT_PROTOCOL
    return _HINT_CLASS


def _is_registered(decorators: Sequence[ast.expr]) -> bool:
    """Return ``True`` when a s0ma registration decorator is present."""
    return any(_decorator_root(decorator) in _REGISTRATION_DECORATORS for decorator in decorators)


def _decorator_root(decorator: ast.expr) -> str:
    """Return a decorator's bare name: ``s0ma.component(...)`` → ``component``."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return _root_name(target)


def _root_name(expression: ast.expr) -> str:
    """Return the rightmost plain name in a dotted or subscripted expression.

    ``Protocol`` from ``typing.Protocol``, ``Protocol`` from
    ``Protocol[T]``, ``Enum`` from ``enum.Enum``. An expression with no
    name in it at all (a call, a lambda) returns the empty string, which
    matches nothing.
    """
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        return expression.attr
    if isinstance(expression, ast.Subscript):
        return _root_name(expression.value)
    return ""


def _unparse_all(expressions: Sequence[ast.expr]) -> tuple[str, ...]:
    """Return *expressions* as normalised source text, source order.

    :func:`ast.unparse` rather than the raw source slice: a decorator
    spread over five lines becomes one readable line, quote styles and
    spacing stop mattering, and the result cannot smuggle a newline or a
    trailing comment into a JSON report. The harvester lifts a
    registration decorator's fields from the tree itself when it needs
    them character-exact, so nothing downstream depends on these strings
    being byte-original.
    """
    return tuple(ast.unparse(expression) for expression in expressions)


# ---------------------------------------------------------------------------
# Module-level facts
# ---------------------------------------------------------------------------


def _literal_dunder_all(tree: ast.Module) -> tuple[str, ...] | None:
    """Return the literal ``__all__`` in declared order, or ``None``.

    ``None`` covers three cases that a scan cannot tell apart and does
    not need to: the module declares no ``__all__``; it builds one from
    an expression; or it declares one and then extends it
    (``__all__ += ...``, ``__all__.extend(...)``). In the last two the
    declared list is not the real export list, so reporting the literal
    part would be worse than reporting nothing. The scan report turns a
    ``None`` on a module that clearly *has* an ``__all__`` into a
    warning.

    Order is as written — not sorted, not de-duplicated. A module's
    ``__all__`` order is authored and the parity comparer is the only
    thing entitled to ignore it.
    """
    literal: tuple[str, ...] | None = None
    declared = False
    for statement in tree.body:
        if _mutates_dunder_all(statement):
            return None
        value = _dunder_all_assignment(statement)
        if value is None:
            continue
        declared = True
        names = _literal_string_sequence(value)
        if names is None:
            return None
        literal = names
    return literal if declared else None


def _dunder_all_assignment(statement: ast.stmt) -> ast.expr | None:
    """Return the expression *statement* assigns to ``__all__``, or ``None``.

    ``None`` means "this statement is not an ``__all__`` assignment".  A
    bare annotation (``__all__: list[str]``) assigns nothing and reads
    the same way.
    """
    if isinstance(statement, ast.Assign):
        assigns = any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        )
        return statement.value if assigns else None
    if isinstance(statement, ast.AnnAssign):
        assigns = isinstance(statement.target, ast.Name) and statement.target.id == "__all__"
        return statement.value if assigns else None
    return None


def _literal_string_sequence(value: ast.expr) -> tuple[str, ...] | None:
    """Return a list/tuple of string literals as written, or ``None``."""
    if not isinstance(value, (ast.List, ast.Tuple)):
        return None
    names: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        names.append(element.value)
    return tuple(names)


def _mutates_dunder_all(statement: ast.stmt) -> bool:
    """Return ``True`` for ``__all__ += ...`` or ``__all__.append/extend(...)``."""
    if isinstance(statement, ast.AugAssign):
        return isinstance(statement.target, ast.Name) and statement.target.id == "__all__"
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        func = statement.value.func
        return (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "__all__"
        )
    return False


def _has_main_guard(tree: ast.Module) -> bool:
    """Return ``True`` when a top-level ``if __name__ == "__main__":`` exists."""
    return any(_is_main_guard(statement) for statement in tree.body)


def _is_main_guard(statement: ast.stmt) -> bool:
    """Return ``True`` for the ``if __name__ == "__main__":`` statement itself."""
    if not isinstance(statement, ast.If):
        return False
    test = statement.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left, right = test.left, test.comparators[0]
    return _is_main_pair(left, right) or _is_main_pair(right, left)


def _is_main_pair(name_side: ast.expr, value_side: ast.expr) -> bool:
    """Return ``True`` when *name_side* is ``__name__`` and *value_side* ``"__main__"``."""
    return (
        isinstance(name_side, ast.Name)
        and name_side.id == "__name__"
        and isinstance(value_side, ast.Constant)
        and value_side.value == "__main__"
    )


def _count_top_level_effects(tree: ast.Module) -> int:
    """Return how many top-level statements actually *do* something on import.

    Not counted: the module docstring, imports, definitions, constant
    assignments, ``__all__`` (declared or extended) and the
    ``__main__`` guard — the things every module has and a conversion
    places automatically.

    Also not counted: an ``if TYPE_CHECKING:`` block containing nothing
    but imports. Strictly it is a conditional statement, but the field
    exists to say "this much work has to be placed by hand", and a
    type-checking import block is placed by the draft's header like any
    other import. Counting it would put a one above zero on nearly every
    typed module and make the number mean nothing.

    Counted: everything else, one per statement — a module-level logger,
    a registry call, a ``try``/``except`` around an import, a loop. Each
    is real work somebody has to decide where to put.
    """
    effects = 0
    for index, statement in enumerate(tree.body):
        if index == 0 and _is_docstring(statement):
            continue
        if isinstance(
            statement,
            (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            continue
        if _is_constant_or_declaration(statement) or _mutates_dunder_all(statement):
            continue
        if _is_main_guard(statement) or _is_type_checking_import_block(statement):
            continue
        effects += 1
    return effects


def _is_constant_or_declaration(statement: ast.stmt) -> bool:
    """Return ``True`` for an ``UPPER_CASE`` (or ``__all__``) assignment.

    A bare annotation without a value (``TOTAL: int``) is a declaration
    and runs nothing, whatever the name's case, so it never counts as an
    effect either.
    """
    if isinstance(statement, ast.AnnAssign):
        if statement.value is None:
            return True
        target = statement.target
        return isinstance(target, ast.Name) and (target.id.isupper() or target.id == "__all__")
    if isinstance(statement, ast.Assign):
        names = _assigned_names(statement.targets)
        return bool(names) and all(name.isupper() or name == "__all__" for name in names)
    return False


def _is_type_checking_import_block(statement: ast.stmt) -> bool:
    """Return ``True`` for an ``if TYPE_CHECKING:`` block of imports only.

    An ``else:`` branch, or any statement that is not an import, makes it
    an ordinary conditional again and it counts as an effect.
    """
    if not isinstance(statement, ast.If) or not _is_type_checking_test(statement.test):
        return False
    if statement.orelse:
        return False
    return all(
        isinstance(inner, (ast.Import, ast.ImportFrom, ast.Pass)) for inner in statement.body
    )


def _is_type_checking_test(test: ast.expr) -> bool:
    """Return ``True`` for ``TYPE_CHECKING`` or ``typing.TYPE_CHECKING``."""
    if isinstance(test, ast.Name):
        return test.id == _TYPE_CHECKING_NAME
    if isinstance(test, ast.Attribute):
        return test.attr == _TYPE_CHECKING_NAME
    return False


def _is_docstring(statement: ast.stmt) -> bool:
    """Return ``True`` for a bare string-literal statement."""
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------


def _package_of(source: SourceFile) -> str:
    """Return the package a module's relative imports resolve against.

    A package's own ``__init__.py`` *is* its package, so ``from . import
    storage`` inside ``bookshelf/__init__.py`` means ``bookshelf.storage``
    and the same line inside ``bookshelf/api.py`` means the same thing —
    but only because the two files answer this question differently.
    """
    if source.path.rsplit("/", 1)[-1] == "__init__.py":
        return source.module
    return source.module.rpartition(".")[0]


def _collect_imports(tree: ast.Module, package: str) -> tuple[ImportFact, ...]:
    """Return every import in the file, in source order.

    Every import anywhere in the module is recorded, with two flags that
    say whether it actually runs: ``deferred`` for an import inside a
    function or method (the usual way a real cycle is made survivable),
    and ``type_checking`` for one under ``if TYPE_CHECKING:`` (which
    never runs at all). The import graph needs both to tell a true
    load-time cycle from a paper one.
    """
    facts: list[ImportFact] = []
    _visit(tree.body, package, deferred=False, type_checking=False, into=facts)
    facts.sort(key=lambda fact: (fact.line, fact.module, fact.names))
    return tuple(facts)


def _visit(
    nodes: Iterable[ast.AST],
    package: str,
    *,
    deferred: bool,
    type_checking: bool,
    into: list[ImportFact],
) -> None:
    """Walk *nodes*, appending an :class:`ImportFact` for every import found."""
    for node in nodes:
        if isinstance(node, ast.Import):
            into.extend(
                ImportFact(
                    module=alias.name,
                    names=(),
                    line=node.lineno,
                    deferred=deferred,
                    type_checking=type_checking,
                    origin=_origin(alias.name),
                )
                for alias in node.names
            )
            continue
        if isinstance(node, ast.ImportFrom):
            target = _resolve_relative(node.module, node.level, package)
            into.append(
                ImportFact(
                    module=target,
                    names=tuple(alias.name for alias in node.names),
                    line=node.lineno,
                    deferred=deferred,
                    type_checking=type_checking,
                    origin=_origin(target),
                )
            )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Everything inside a function body — including a method's,
            # including a function nested in a class — runs on call, not
            # on import.
            _visit(node.body, package, deferred=True, type_checking=type_checking, into=into)
            continue
        if isinstance(node, ast.If):
            branch = type_checking or _is_type_checking_test(node.test)
            _visit(node.body, package, deferred=deferred, type_checking=branch, into=into)
            # The ``else:`` of a TYPE_CHECKING block is the runtime
            # branch — it is exactly where the real import lives.
            _visit(node.orelse, package, deferred=deferred, type_checking=type_checking, into=into)
            continue
        _visit(
            ast.iter_child_nodes(node),
            package,
            deferred=deferred,
            type_checking=type_checking,
            into=into,
        )


def _resolve_relative(module: str | None, level: int, package: str) -> str:
    """Return an import target as an absolute dotted name.

    ``from . import x`` inside ``bookshelf.api`` is ``bookshelf``;
    ``from .storage import S`` is ``bookshelf.storage``; ``from ..util
    import f`` climbs one package further.

    A relative import that climbs *past* the top of the project is not
    resolvable — it is the same "attempted relative import beyond
    top-level package" Python itself refuses — so it keeps its literal
    written spelling (``".."``, ``"..util"``) and stays
    ``"unresolved"``. The leading dot is the agreed signal: the import
    graph reads a ``module`` that is empty or starts with ``"."`` as
    "this one could not be resolved, do not try to match it", and every
    import that *can* be resolved is recorded as a plain dotted name
    with no leading dot.

    The depth rule matches CPython's own (``importlib``'s
    ``_resolve_name``): *level* dots need *level* - 1 packages above the
    current one, so ``from ..x import y`` inside the top-level package
    ``bookshelf`` is beyond the top, and so is any relative import in a
    module that belongs to no package at all.
    """
    if level == 0:
        return module or ""
    parts = package.split(".") if package else []
    keep = len(parts) - (level - 1)
    if keep <= 0:
        return "." * level + (module or "")
    base = parts[:keep]
    if module:
        base = [*base, module]
    return ".".join(base)


def _origin(module: str) -> str:
    """Return ``"stdlib"`` when the interpreter ships *module*, else ``"unresolved"``.

    Telling a first-party module from a third-party one needs the list of
    modules this project actually contains, which the census does not
    have; ``adopt/graph.py`` holds that and re-classifies what is left.
    """
    top = module.partition(".")[0]
    if top and top in sys.stdlib_module_names:
        return _ORIGIN_STDLIB
    return _ORIGIN_UNRESOLVED
