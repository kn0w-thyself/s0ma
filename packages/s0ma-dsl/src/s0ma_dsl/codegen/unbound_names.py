"""Find the names an emitted module reads before anything has bound them.

``compile()`` does not resolve global names, so a module whose signature
says ``-> dict[str, Any]`` with no ``typing.Any`` in ``requires:`` used to
check clean, build, and raise ``NameError`` on import. This walks the
emitted text, which already holds everything that can bind a name (declared
imports, framework imports, soft-require fallbacks, deferred imports,
privileged imports), and reports each global read that no module-level
binding or builtin covers, and each load read that runs before its binding.

A read is one of two kinds, and the answer is the same on every Python:

* **At load**: executed when the module is imported on Python 3.11 to 3.13.
  Module-level statements, module-level class bodies, and the decorators,
  defaults, and annotations of their functions. An annotation counts even
  when the check runs on 3.14 or later, where it is evaluated lazily,
  because the same source fails on the older versions it supports.
* **In a body**: read only when a function runs, including the signature of
  a nested ``def``.

The walk uses ``ast`` rather than ``symtable``, which treats a function
named ``top`` as the module scope and reports local variable annotations on
some Python versions and not on others.

A false error on a working module is worse than a miss, so the analysis
stays silent when it cannot know. A star import, ``globals()``, ``exec``,
``eval``, ``sys.modules[__name__]``, and a write to ``builtins`` make the
module's unresolved names unknowable. A read inside a ``try`` that catches
``NameError`` is deliberate. At load, so is one under a bare ``except:`` or a
handler naming ``Exception`` or ``BaseException``, because the module still
imports. In a function body the same broad handler is no guard, because that
is how a removed ``uses:`` entry gets swallowed, so the read stays reported.
A class with an explicit ``metaclass=`` may supply names through
``__prepare__``. The bounds and values of PEP 695 type parameters and aliases
are evaluated lazily and are not read.

A module that reaches its own module object can also write names no walk
sees, so any use of ``sys.modules``, ``importlib.import_module``, or an import
of the module by its own name stops the analysis too.

**Load order.** A name with a module-level binding is reported when a read
that always runs comes before every statement that binds it, or when its
only bindings are in the true branch of ``if TYPE_CHECKING:``. A class or
function binds its name when its statement ends, so a method annotation that
names its own class is a read before binding. "Always runs" is strict: a
read in a branch, a loop body, any part of ``try``, a ``with`` body, a
``match`` case, the right of ``and`` or ``or``, a ternary's arms, a later
comparison operand, a comprehension past its first iterable, or an
``assert`` is left alone, because the module may load without running it.
Reads inside function bodies are not judged for order.

Annotations are lazy from Python 3.14, so an annotation read is reported
under this rule only when the project's ``requires-python`` admits 3.11,
3.12, or 3.13. With no declared range, or a clause that cannot be read, it
stays silent. A default, value, base class, or decorator fails on every
Python and is reported whatever the range.
"""

from __future__ import annotations

import ast
import builtins
import re
import typing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from s0ma_dsl.codegen.source_map import SourceMapGenerator, resolve_output_line
from s0ma_dsl.config import get_severity
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.config import StrictnessMode

_ScopeKind = Literal["module", "class", "function", "comprehension", "type_params"]

#: Why a load read found nothing: no binding at all, one further down the
#: file, the class still being defined, or one under ``if TYPE_CHECKING:``.
_ReadCause = Literal["unbound", "later", "own_name", "type_checking"]

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
_TRIES = (ast.Try, ast.TryStar)
#: ``ast.TypeAlias`` exists from Python 3.12.
_TYPE_ALIAS: tuple[type[ast.AST], ...] = (
    (ast.TypeAlias,) if hasattr(ast, "TypeAlias") else ()
)

#: Names every module has before its first line runs.
_MODULE_NAMES = frozenset({
    "__annotate__", "__annotations__", "__builtins__", "__cached__",
    "__conditional_annotations__", "__debug__", "__doc__", "__file__",
    "__loader__", "__name__", "__package__", "__path__", "__spec__",
})

#: Names a class body has before its first line runs.
_CLASS_BODY_NAMES = frozenset({
    "__annotate__", "__annotations__", "__classdict__",
    "__conditional_annotations__", "__doc__", "__firstlineno__",
    "__module__", "__qualname__", "__static_attributes__",
})

#: Builtins that exist only on some Pythons or platforms, or that ``site``
#: installs, listed so one source gets one answer everywhere. ``_`` is the
#: name ``gettext.install`` puts in builtins.
_OTHER_BUILTINS = frozenset({
    "PythonFinalizationError", "WindowsError", "_", "_IncompleteInputError",
    "copyright", "credits", "exit", "frozendict", "help", "license", "quit",
})

_ALWAYS_BOUND = frozenset(dir(builtins)) | _MODULE_NAMES | _OTHER_BUILTINS

#: Calling one of these builtins can create a global no walk can see.
_NAMESPACE_WRITERS = frozenset({"eval", "exec", "globals"})

#: Calling one of these can hand a module its own module object.
_MODULE_LOADERS = frozenset({"__import__", "import_module"})

#: The loader the emitter writes for a ``uses:`` entry that shadows a stdlib
#: module. It touches ``sys.modules`` under a mangled key of its own, so it
#: says nothing about this module's namespace.
_SHADOWED_LOADER = "_s0ma_import_shadowed"

#: The two names a ``TYPE_CHECKING`` guard is spelled with.
_GUARD_NAMES = frozenset({"TYPE_CHECKING", "typing"})

#: Calling one of these on a module object can write to its namespace.
_ATTRIBUTE_WRITERS = frozenset({"delattr", "setattr", "vars"})

#: Attributes that hand over a live globals dictionary.
_GLOBALS_ATTRIBUTES = frozenset({"__globals__", "f_globals", "f_locals"})

#: One ``requires-python`` clause, whole. A pre-release, a local version, or
#: anything else this does not match is a clause that cannot be read.
_VERSION_CLAUSE = re.compile(
    r"\s*(==|!=|<=|>=|<|>|~=)\s*(\d+(?:\.\d+){0,2})(\.\*)?\s*"
)

#: The minor versions of Python 3 that evaluate annotations as they load.
_EAGER_ANNOTATION_MINORS = (11, 12, 13)


@dataclass(frozen=True)
class UnboundRead:
    """One name nothing has bound, at the first place the module reads it."""

    name: str
    line: int
    at_load: bool
    read_count: int = 1
    cause: _ReadCause = "unbound"
    #: Every reported read of the name is an annotation, so it fails only
    #: on the Pythons that evaluate annotations at load.
    annotation_only: bool = False


@dataclass(eq=False)
class _Scope:
    kind: _ScopeKind
    parent: _Scope | None
    bound: set[str] = field(default_factory=set)
    #: A class body whose metaclass may answer for names it does not hold.
    open_namespace: bool = False


def _argument_nodes(arguments: ast.arguments) -> list[ast.arg]:
    nodes = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    if arguments.vararg is not None:
        nodes.append(arguments.vararg)
    if arguments.kwarg is not None:
        nodes.append(arguments.kwarg)
    return nodes


def _default_nodes(arguments: ast.arguments) -> list[ast.expr]:
    return [
        *arguments.defaults,
        *(node for node in arguments.kw_defaults if node is not None),
    ]


def _annotation_nodes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[ast.expr]:
    annotations = [
        arg.annotation
        for arg in _argument_nodes(node.args)
        if arg.annotation is not None
    ]
    if node.returns is not None:
        annotations.append(node.returns)
    return annotations


def _walrus_targets(comprehension: ast.expr) -> set[str]:
    """Names a comprehension's walruses bind in the scope around it."""
    names: set[str] = set()
    stack: list[ast.AST] = [comprehension]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.NamedExpr):
            names.add(node.target.id)
            stack.append(node.value)
        elif isinstance(node, ast.Lambda):
            stack.extend(_default_nodes(node.args))
        else:
            stack.extend(ast.iter_child_nodes(node))
    return names


def _bind(
    scope: _Scope,
    roots: Iterable[ast.AST],
    *,
    never_runs: Callable[[ast.expr], bool] | None = None,
) -> None:
    """Add what *roots* bind in *scope*, without entering nested scopes.

    An ``if`` whose test satisfies *never_runs* contributes only its
    ``else``, because its true branch does not run when the module loads.
    """
    stack = list(roots)
    while stack:
        node = stack.pop()
        if (
            never_runs is not None
            and isinstance(node, ast.If)
            and never_runs(node.test)
        ):
            stack.append(node.test)
            stack.extend(node.orelse)
        elif isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load):
                scope.bound.add(node.id)
        elif isinstance(node, _FUNCTIONS):
            scope.bound.add(node.name)
            stack.extend(node.decorator_list)
            stack.extend(_default_nodes(node.args))
            stack.extend(_annotation_nodes(node))
        elif isinstance(node, ast.ClassDef):
            scope.bound.add(node.name)
            stack.extend(node.decorator_list)
            stack.extend(node.bases)
            stack.extend(node.keywords)
        elif isinstance(node, ast.Lambda):
            stack.extend(_default_nodes(node.args))
        elif isinstance(node, _COMPREHENSIONS):
            scope.bound.update(_walrus_targets(node))
        elif isinstance(node, ast.Import):
            scope.bound.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            scope.bound.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Nonlocal):
            scope.bound.update(node.names)
        elif _TYPE_ALIAS and isinstance(node, _TYPE_ALIAS):
            # The alias's name is its one stored ``Name``. Its value and
            # parameters belong to scopes of their own.
            stack.extend(
                child for child in ast.iter_child_nodes(node)
                if isinstance(child, ast.Name)
            )
        else:
            if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                if node.name:
                    scope.bound.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                scope.bound.add(node.rest)
            stack.extend(ast.iter_child_nodes(node))


def _bound_in_scopes(name: str, scope: _Scope) -> bool:
    """Resolve a read through the enclosing scopes, by Python's rules.

    A class body's names are visible to the class body itself and to the
    annotation scope of a generic method, and to nothing nested deeper.
    """
    class_visible = True
    current: _Scope | None = scope
    while current is not None:
        if current.kind == "class":
            if class_visible and (
                name in current.bound
                or name in _CLASS_BODY_NAMES
                or current.open_namespace
            ):
                return True
        elif name in current.bound:
            return True
        if current.kind != "type_params":
            class_visible = False
        current = current.parent
    return False


def _inside_class(scope: _Scope) -> bool:
    current: _Scope | None = scope
    while current is not None:
        if current.kind == "class":
            return True
        current = current.parent
    return False


def _is_bound(name: str, scope: _Scope) -> bool:
    return (
        _bound_in_scopes(name, scope)
        or name in _ALWAYS_BOUND
        or (name == "__class__" and _inside_class(scope))
    )


def _catches_name_error(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    candidates = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(
        isinstance(item, ast.Name) and item.id == "NameError"
        for item in candidates
    )


def _is_broad_handler(handler: ast.ExceptHandler) -> bool:
    """Whether *handler* is bare or names ``Exception`` or ``BaseException``."""
    caught = handler.type
    if caught is None:
        return True
    candidates = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(
        isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"}
        for item in candidates
    )


def _opens_the_namespace(node: ast.AST, scope: _Scope) -> bool:
    """Whether *node* can create module globals that no walk can see."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name in _NAMESPACE_WRITERS:
            return not _bound_in_scopes(name, scope)
        # With no argument these two are the module's or class's own
        # namespace, and a write through them binds a name.
        return (
            name in {"locals", "vars"}
            and not node.args
            and not node.keywords
            and scope.kind in {"module", "class"}
        )
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return isinstance(node.value, ast.Name) and node.value.id == "builtins"
    return False


def _writes_through(nodes: list[ast.AST], name: str) -> bool:
    """Whether *nodes* write to the object *name* holds, as far as they show."""
    for node in nodes:
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id != name:
                continue
            if not isinstance(node.ctx, ast.Load) or node.attr == "__dict__":
                return True
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _ATTRIBUTE_WRITERS
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == name
        ):
            return True
    return False


def _imports_itself(nodes: list[ast.AST], module_name: str) -> bool:
    """Whether the module imports itself by its own name.

    The bare name and a relative import of it are the module. A dotted path
    ending in the same word may be the module under its package, or may be
    another module entirely (``from django.db import models`` in a module
    called ``models``), so that form counts only when the module writes to
    what it imported.
    """
    leaf = module_name.rsplit(".", 1)[-1]
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    return True
                if alias.name.rsplit(".", 1)[-1] == leaf and (
                    alias.asname is None or _writes_through(nodes, alias.asname)
                ):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name and not node.level:
                return True
            if node.level and node.module == leaf:
                return True
            for alias in node.names:
                if alias.name != leaf:
                    continue
                if node.level and node.module is None:
                    return True
                if _writes_through(nodes, alias.asname or alias.name):
                    return True
    return False


def _reaches_its_own_module(tree: ast.Module, module_name: str | None) -> bool:
    """Whether the module can reach its own namespace by a route no walk sees.

    That is its module object (``sys.modules``, ``import_module``, importing
    itself), a live globals dictionary, or a write to ``builtins``.
    """
    nodes = [
        node
        for statement in tree.body
        if not (
            isinstance(statement, _FUNCTIONS) and statement.name == _SHADOWED_LOADER
        )
        for node in ast.walk(statement)
    ]
    sys_names = {"sys"}
    builtins_names = {"builtins"}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname and alias.name == "sys":
                    sys_names.add(alias.asname)
                elif alias.asname and alias.name == "builtins":
                    builtins_names.add(alias.asname)
    if any(_writes_through(nodes, name) for name in builtins_names):
        return True
    for node in nodes:
        if isinstance(node, ast.Attribute):
            if node.attr == "import_module" or node.attr in _GLOBALS_ATTRIBUTES:
                return True
            if (
                node.attr == "modules"
                and isinstance(node.value, ast.Name)
                and node.value.id in sys_names
            ):
                return True
        elif isinstance(node, ast.Name):
            if node.id in _MODULE_LOADERS or node.id == "__builtins__":
                return True
        elif isinstance(node, ast.ImportFrom) and not node.level:
            imported = {alias.name for alias in node.names}
            if (node.module == "sys" and "modules" in imported) or (
                node.module == "importlib" and "import_module" in imported
            ):
                return True
    return module_name is not None and _imports_itself(nodes, module_name)


class _Reader:
    """Walks one module and records every read nothing binds."""

    def __init__(self, future_annotations: bool) -> None:
        self.future_annotations = future_annotations
        self.namespace_is_open = False
        self.load_reads: dict[str, list[int]] = {}
        self.body_reads: dict[str, list[int]] = {}
        self._stack: list[tuple[ast.AST, _Scope, bool, bool]] = []

    def _push(
        self,
        nodes: Iterable[ast.AST],
        scope: _Scope,
        at_load: bool,
        guarded: bool,
    ) -> None:
        self._stack.extend((node, scope, at_load, guarded) for node in nodes)

    def walk(self, tree: ast.Module, module_scope: _Scope) -> None:
        self._push(tree.body, module_scope, True, False)
        while self._stack:
            node, scope, at_load, guarded = self._stack.pop()
            if _opens_the_namespace(node, scope):
                self.namespace_is_open = True
                return
            self._visit(node, scope, at_load, guarded)

    def _visit(
        self, node: ast.AST, scope: _Scope, at_load: bool, guarded: bool,
    ) -> None:
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and not guarded:
                self._read(node, scope, at_load)
        elif isinstance(node, _FUNCTIONS):
            self._visit_function(node, scope, at_load, guarded)
        elif isinstance(node, ast.Lambda):
            self._push(_default_nodes(node.args), scope, at_load, guarded)
            inner = _Scope("function", scope)
            inner.bound.update(arg.arg for arg in _argument_nodes(node.args))
            _bind(inner, [node.body])
            self._push([node.body], inner, False, False)
        elif isinstance(node, ast.ClassDef):
            self._visit_class(node, scope, at_load, guarded)
        elif isinstance(node, _COMPREHENSIONS):
            self._visit_comprehension(node, scope, at_load, guarded)
        elif isinstance(node, ast.AnnAssign):
            self._push([node.target], scope, at_load, guarded)
            if node.value is not None:
                self._push([node.value], scope, at_load, guarded)
            # A local variable's annotation is never evaluated.
            if scope.kind in {"module", "class"} and not self.future_annotations:
                self._push([node.annotation], scope, at_load, guarded)
        elif isinstance(node, _TRIES):
            body_guarded = guarded or any(
                _catches_name_error(handler)
                or (at_load and _is_broad_handler(handler))
                for handler in node.handlers
            )
            self._push(node.body, scope, at_load, body_guarded)
            self._push(node.handlers, scope, at_load, guarded)
            self._push(node.orelse, scope, at_load, guarded)
            self._push(node.finalbody, scope, at_load, guarded)
        elif _TYPE_ALIAS and isinstance(node, _TYPE_ALIAS):
            return
        else:
            self._push(ast.iter_child_nodes(node), scope, at_load, guarded)

    def _read(self, node: ast.Name, scope: _Scope, at_load: bool) -> None:
        if _is_bound(node.id, scope):
            return
        reads = self.load_reads if at_load else self.body_reads
        reads.setdefault(node.id, []).append(node.lineno)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        scope: _Scope,
        at_load: bool,
        guarded: bool,
    ) -> None:
        self._push(node.decorator_list, scope, at_load, guarded)
        self._push(_default_nodes(node.args), scope, at_load, guarded)
        signature_scope = _type_param_scope(node, scope)
        if not self.future_annotations:
            self._push(_annotation_nodes(node), signature_scope, at_load, guarded)
        inner = _Scope("function", signature_scope)
        inner.bound.update(arg.arg for arg in _argument_nodes(node.args))
        _bind(inner, node.body)
        self._push(node.body, inner, False, False)

    def _visit_class(
        self, node: ast.ClassDef, scope: _Scope, at_load: bool, guarded: bool,
    ) -> None:
        self._push(node.decorator_list, scope, at_load, guarded)
        header_scope = _type_param_scope(node, scope)
        self._push(node.bases, header_scope, at_load, guarded)
        self._push(node.keywords, header_scope, at_load, guarded)
        inner = _Scope(
            "class",
            header_scope,
            open_namespace=any(k.arg == "metaclass" for k in node.keywords),
        )
        _bind(inner, node.body)
        self._push(node.body, inner, at_load, guarded)

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        scope: _Scope,
        at_load: bool,
        guarded: bool,
    ) -> None:
        # The first iterable runs in the enclosing scope, right away. The
        # rest of a generator expression runs only when it is consumed.
        self._push([node.generators[0].iter], scope, at_load, guarded)
        inner_load = at_load and not isinstance(node, ast.GeneratorExp)
        inner = _Scope("comprehension", scope)
        for index, generator in enumerate(node.generators):
            inner.bound.update(
                sub.id
                for sub in ast.walk(generator.target)
                if isinstance(sub, ast.Name) and not isinstance(sub.ctx, ast.Load)
            )
            if index:
                self._push([generator.iter], inner, inner_load, guarded)
            self._push([generator.target], inner, inner_load, guarded)
            self._push(generator.ifs, inner, inner_load, guarded)
        if isinstance(node, ast.DictComp):
            results: list[ast.AST] = [node.key, node.value]
        else:
            results = [node.elt]
        self._push(results, inner, inner_load, guarded)


def _type_param_scope(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    scope: _Scope,
) -> _Scope:
    """The scope a PEP 695 parameter list adds, or *scope* when it has none."""
    type_params = getattr(node, "type_params", ())
    if not type_params:
        return scope
    return _Scope(
        "type_params", scope, bound={param.name for param in type_params},
    )


def _parse_range_clause(
    clause: str,
) -> tuple[str, tuple[int, int, int], int, bool] | None:
    """Read one clause as (operator, release, segments written, wildcard)."""
    match = _VERSION_CLAUSE.fullmatch(clause)
    if match is None:
        return None
    operator, written, wildcard = match.groups()
    parts = [int(part) for part in written.split(".")]
    if wildcard and operator not in {"==", "!="}:
        return None
    if operator == "~=" and len(parts) < 2:
        return None
    padded = (parts + [0, 0])[:3]
    return operator, (padded[0], padded[1], padded[2]), len(parts), bool(wildcard)


def _clause_admits(
    clause: tuple[str, tuple[int, int, int], int, bool],
    candidate: tuple[int, int, int],
) -> bool:
    operator, release, segments, wildcard = clause
    if operator == ">=":
        return candidate >= release
    if operator == ">":
        return candidate > release
    if operator == "<=":
        return candidate <= release
    if operator == "<":
        return candidate < release
    if operator == "~=":
        return candidate >= release and (
            candidate[:segments - 1] == release[:segments - 1]
        )
    same = (
        candidate[:segments] == release[:segments]
        if wildcard
        else candidate == release
    )
    return same if operator == "==" else not same


def _annotations_run_at_load(requires_python: tuple[str, ...] | None) -> bool:
    """Whether the declared range admits a Python that evaluates annotations.

    The answer is yes when some release of 3.11, 3.12, or 3.13 satisfies
    every clause. No range, or any clause that cannot be read, is no: the
    finding is an error, and an error needs a floor the project declared.
    """
    if not requires_python:
        return False
    clauses = []
    for text in requires_python:
        clause = _parse_range_clause(text)
        if clause is None:
            return False
        clauses.append(clause)
    for minor in _EAGER_ANNOTATION_MINORS:
        # The releases a range admits start at .0, at a clause's own patch,
        # or just past it, so these are the only ones that need testing.
        patches = {0}
        for _, release, _, _ in clauses:
            if release[:2] == (3, minor):
                patches.update((release[2], release[2] + 1))
        if any(
            all(_clause_admits(clause, (3, minor, patch)) for clause in clauses)
            for patch in patches
        ):
            return True
    return False


def load_order_cache_key(requires_python: tuple[str, ...] | None) -> str:
    """The part of a build's cache key the load-order answer depends on.

    A build that hits the cache runs no check, so a range that changes
    whether annotation reads are errors has to miss.
    """
    return f"annotations-run-at-load:{_annotations_run_at_load(requires_python)}"


def _type_checking_names(tree: ast.Module) -> frozenset[str]:
    """Which ``TYPE_CHECKING`` spellings are certainly false at load.

    ``TYPE_CHECKING`` counts when it comes from ``typing`` or
    ``typing_extensions`` and ``typing`` when it is that module, and neither
    is bound to anything else anywhere in the file. A project that sets its
    own ``TYPE_CHECKING = True`` runs that branch, so its names are real.
    """
    imported: set[str] = set()
    rebound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                if (
                    bound == "TYPE_CHECKING"
                    and alias.name == "TYPE_CHECKING"
                    and not node.level
                    and node.module in {"typing", "typing_extensions"}
                ):
                    imported.add(bound)
                elif bound in _GUARD_NAMES:
                    rebound.add(bound)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if alias.name == "typing" and bound == "typing":
                    imported.add(bound)
                elif bound in _GUARD_NAMES:
                    rebound.add(bound)
        elif isinstance(node, ast.Attribute):
            if node.attr == "TYPE_CHECKING" and not isinstance(node.ctx, ast.Load):
                rebound.update(_GUARD_NAMES)
        elif isinstance(node, ast.Name):
            if not isinstance(node.ctx, ast.Load) and node.id in _GUARD_NAMES:
                rebound.add(node.id)
        elif isinstance(
            node,
            (*_FUNCTIONS, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar),
        ):
            if node.name in _GUARD_NAMES:
                rebound.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest in _GUARD_NAMES:
            rebound.add(node.rest)
    return frozenset(imported - rebound)


def _always_read_names(root: ast.AST) -> Iterator[ast.Name]:
    """The names *root* reads on every evaluation of it.

    Past a short circuit, a ternary's test, a comparison's first operand,
    or a comprehension's first iterable, a read may never run. A lambda runs
    only its defaults when it is created.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                yield node
        elif isinstance(node, ast.Lambda):
            stack.extend(_default_nodes(node.args))
        elif isinstance(node, _COMPREHENSIONS):
            stack.append(node.generators[0].iter)
        elif isinstance(node, ast.IfExp):
            stack.append(node.test)
        elif isinstance(node, ast.BoolOp):
            stack.append(node.values[0])
        elif isinstance(node, ast.Compare):
            stack.append(node.left)
        elif isinstance(node, ast.NamedExpr):
            stack.append(node.value)
        else:
            stack.extend(ast.iter_child_nodes(node))


@dataclass(frozen=True)
class _ClassFrame:
    """The class body a read is in."""

    name: str
    binds: frozenset[str]
    open_namespace: bool


@dataclass(frozen=True)
class _ReadSite:
    """Where a load read happens."""

    frame: _ClassFrame | None = None
    #: The enclosing classes, which are unbound until their statements end.
    classes: frozenset[str] = frozenset()
    #: PEP 695 parameters in scope.
    parameters: frozenset[str] = frozenset()
    annotation: bool = False


@dataclass(frozen=True)
class _OrderedRead:
    line: int
    cause: _ReadCause
    annotation: bool


class _LoadOrder:
    """Walks the statements that always run, in the order they run."""

    def __init__(
        self,
        tree: ast.Module,
        module_bound: set[str],
        declared_global: set[str],
        *,
        future_annotations: bool,
        annotations_run: bool,
    ) -> None:
        guards = _type_checking_names(tree)
        self._never_runs = lambda test: _is_type_checking_test(test, guards)
        runtime = _Scope("module", None)
        _bind(runtime, tree.body, never_runs=self._never_runs)
        self._runtime_bound = runtime.bound | declared_global
        self._module_bound = module_bound
        self._future_annotations = future_annotations
        self._annotations_run = annotations_run
        self._bound_now = set(declared_global)
        self._assigned = self._names_assigned_at_top(tree)
        self._open_classes: set[str] = set()
        self.reads: dict[str, list[_OrderedRead]] = {}

    @staticmethod
    def _names_assigned_at_top(tree: ast.Module) -> set[str]:
        """Module names bound by something other than a class or an import."""
        assigned = _Scope("module", None)
        _bind(assigned, (
            statement for statement in tree.body
            if not isinstance(statement, (ast.ClassDef, ast.Import, ast.ImportFrom))
        ))
        return assigned.bound

    def run(self, body: list[ast.stmt], site: _ReadSite) -> None:
        for statement in body:
            self._statement(statement, site)

    def _read(self, roots: Iterable[ast.AST], site: _ReadSite) -> None:
        for root in roots:
            for node in _always_read_names(root):
                self._read_name(node.id, node.lineno, site)

    def _read_name(self, name: str, line: int, site: _ReadSite) -> None:
        if name in _ALWAYS_BOUND or name in site.parameters:
            return
        frame = site.frame
        if frame is not None and (
            frame.open_namespace
            or name in frame.binds
            or name in _CLASS_BODY_NAMES
        ):
            return
        if name in self._bound_now or name not in self._module_bound:
            return
        if site.annotation and not self._annotations_run:
            return
        cause: _ReadCause
        if name not in self._runtime_bound:
            cause = "type_checking"
        elif name in site.classes:
            cause = "own_name"
        else:
            cause = "later"
        self.reads.setdefault(name, []).append(
            _OrderedRead(line, cause, site.annotation),
        )

    def _bind_now(self, roots: Iterable[ast.AST], site: _ReadSite) -> None:
        """Record what *roots* bind. A class body's names live in its frame."""
        if site.frame is not None:
            return
        scope = _Scope("module", None)
        _bind(scope, roots, never_runs=self._never_runs)
        self._bound_now |= scope.bound

    def _statement(self, node: ast.stmt, site: _ReadSite) -> None:
        if isinstance(node, _FUNCTIONS):
            self._function(node, site)
        elif isinstance(node, ast.ClassDef):
            self._class(node, site)
        elif isinstance(node, ast.Assign):
            self._assign(node.value, node.targets, site)
        elif isinstance(node, ast.AugAssign):
            self._bind_now([node.value], site)
            if isinstance(node.target, ast.Name):
                self._read_name(node.target.id, node.lineno, site)
            else:
                self._read([node.target], site)
            self._read([node.value], site)
            self._bind_now([node.target], site)
        elif isinstance(node, ast.AnnAssign):
            self._annotated(node, site)
        elif isinstance(node, (ast.If, ast.While)):
            self._header_then_branches(node.test, node, site)
        elif isinstance(node, ast.For):
            self._header_then_branches(node.iter, node, site)
        elif isinstance(node, ast.With):
            # A later item runs inside the earlier ones, which can swallow it.
            self._header_then_branches(node.items[0].context_expr, node, site)
        elif isinstance(node, ast.Match):
            self._header_then_branches(node.subject, node, site)
        elif isinstance(node, ast.Expr):
            self._bind_now([node.value], site)
            self._read([node.value], site)
        elif isinstance(node, ast.Raise):
            parts = [part for part in (node.exc, node.cause) if part is not None]
            self._bind_now(parts, site)
            self._read(parts, site)
        elif isinstance(node, ast.Delete):
            self._read(
                (t for t in node.targets if not isinstance(t, ast.Name)), site,
            )
        else:
            # ``try`` and ``assert`` may not run what they hold, and the
            # rest (imports, ``type`` aliases) only bind.
            self._bind_now([node], site)

    def _assign(
        self, value: ast.expr, targets: list[ast.expr], site: _ReadSite,
    ) -> None:
        self._bind_now([value], site)
        self._read([value], site)
        # A target can read a name an earlier target just bound
        # (``i, items[i] = 0, 1``), so the names land first.
        self._bind_now(targets, site)
        self._read(targets, site)

    def _annotated(self, node: ast.AnnAssign, site: _ReadSite) -> None:
        annotation = _ReadSite(
            site.frame, site.classes, site.parameters, annotation=True,
        )
        if node.value is not None:
            self._assign(node.value, [node.target], site)
        if not self._future_annotations:
            self._read([node.annotation], annotation)

    def _header_then_branches(
        self, header: ast.expr, node: ast.stmt, site: _ReadSite,
    ) -> None:
        """Read the part that always runs, then bind what the rest may."""
        self._bind_now([header], site)
        self._read([header], site)
        self._bind_now([node], site)

    def _function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, site: _ReadSite,
    ) -> None:
        defaults = _default_nodes(node.args)
        annotations = _annotation_nodes(node)
        self._bind_now([*node.decorator_list, *defaults, *annotations], site)
        self._read(node.decorator_list, site)
        self._read(defaults, site)
        if not self._future_annotations:
            signature = _ReadSite(
                site.frame,
                site.classes,
                site.parameters | _type_parameters(node),
                annotation=True,
            )
            self._read(annotations, signature)
        self._bind_now_name(node.name, site)

    def _class(self, node: ast.ClassDef, site: _ReadSite) -> None:
        # The value of ``metaclass=`` is left alone with the namespace it opens.
        keywords = [k.value for k in node.keywords if k.arg != "metaclass"]
        header = [*node.decorator_list, *node.bases, *keywords]
        self._bind_now(header, site)
        parameters = site.parameters | _type_parameters(node)
        self._read(node.decorator_list, site)
        self._read([*node.bases, *keywords], _ReadSite(
            site.frame, site.classes, parameters,
        ))
        scope = _Scope("class", None)
        _bind(scope, node.body)
        opened = self._opens_its_namespace(node)
        if opened:
            self._open_classes.add(node.name)
        frame = _ClassFrame(node.name, frozenset(scope.bound), opened)
        self.run(node.body, _ReadSite(
            frame, site.classes | {node.name}, parameters,
        ))
        self._bind_now_name(node.name, site)

    def _opens_its_namespace(self, node: ast.ClassDef) -> bool:
        """Whether the class's metaclass could answer for names it reads.

        An explicit ``metaclass=`` can, and it is inherited, so a class built
        on an open class in this module is open too. So is a base this walk
        cannot name (a call, a starred list, a module-level variable holding
        anything) and a ``**`` that may carry ``metaclass``.
        """
        if any(keyword.arg in {"metaclass", None} for keyword in node.keywords):
            return True
        return any(self._base_may_open(base) for base in node.bases)

    def _base_may_open(self, base: ast.expr) -> bool:
        if isinstance(base, ast.Subscript):
            return self._base_may_open(base.value)
        if isinstance(base, ast.Attribute):
            return False
        if isinstance(base, ast.Name):
            return base.id in self._open_classes or base.id in self._assigned
        return True

    def _bind_now_name(self, name: str, site: _ReadSite) -> None:
        if site.frame is None:
            self._bound_now.add(name)


def _is_type_checking_test(test: ast.expr, guards: frozenset[str]) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING" and test.id in guards
    return (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and "typing" in guards
    )


def _type_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> frozenset[str]:
    return frozenset(param.name for param in getattr(node, "type_params", ()))


def _load_order_reads(
    tree: ast.Module,
    module_bound: set[str],
    declared_global: set[str],
    *,
    future_annotations: bool,
    requires_python: tuple[str, ...] | None,
) -> list[UnboundRead]:
    """Each bound name a load read reaches before its binding."""
    walk = _LoadOrder(
        tree,
        module_bound,
        declared_global,
        future_annotations=future_annotations,
        annotations_run=_annotations_run_at_load(requires_python),
    )
    walk.run(tree.body, _ReadSite())
    found = []
    for name, reads in walk.reads.items():
        first = min(reads, key=lambda read: read.line)
        found.append(UnboundRead(
            name,
            first.line,
            True,
            len(reads),
            first.cause,
            annotation_only=all(read.annotation for read in reads),
        ))
    return found


def find_unbound_names(
    python_source: str,
    *,
    module_name: str | None = None,
    requires_python: tuple[str, ...] | None = None,
) -> list[UnboundRead]:
    """Every name *python_source* reads with nothing bound, first read first.

    A name read both at load and in a body is reported once, as a load read:
    that is the failure the module hits first. Text that does not parse
    returns nothing, because the build reports it elsewhere. *module_name*
    lets the walk see a module importing itself. *requires_python* decides
    whether an annotation read before its binding is reported.
    """
    try:
        tree = ast.parse(python_source)
    except (SyntaxError, ValueError, RecursionError):
        return []

    module_scope = _Scope("module", None)
    declared_global: set[str] = set()
    future_annotations = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            # A declared global is the author saying the module holds it.
            declared_global.update(node.names)
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            if "*" in names:
                return []
            if node.module == "__future__" and "annotations" in names:
                future_annotations = True
    if _reaches_its_own_module(tree, module_name):
        return []
    module_scope.bound.update(declared_global)
    _bind(module_scope, tree.body)

    reader = _Reader(future_annotations)
    reader.walk(tree, module_scope)
    if reader.namespace_is_open:
        return []

    found = [
        UnboundRead(name, min(lines), True, len(lines))
        for name, lines in reader.load_reads.items()
    ]
    found.extend(
        UnboundRead(name, min(lines), False, len(lines))
        for name, lines in reader.body_reads.items()
        if name not in reader.load_reads
    )
    found.extend(_load_order_reads(
        tree,
        module_scope.bound,
        declared_global,
        future_annotations=future_annotations,
        requires_python=requires_python,
    ))
    return sorted(found, key=lambda read: (read.line, read.name))


def _fix_for(name: str) -> str:
    """The header entry to suggest for *name*."""
    if name in typing.__all__:
        # A lowercase last segment needs the colon form to be a from-import.
        entry = f"typing.{name}" if name[0].isupper() else f"typing:{name}"
        return f"add `{entry}` to `requires:`"
    return (
        "declare it in the module header (`requires:` for a Python import, "
        "`uses:` for a s0ma component), or correct the name if it is a typo"
    )


def _load_order_text(read: UnboundRead) -> tuple[str, str]:
    """Why this read has nothing bound yet, and how to fix it."""
    name = read.name
    if read.cause == "type_checking":
        why = (
            "its only binding is under `if TYPE_CHECKING:`, which does not "
            "run when the module loads"
        )
        fix = (
            f"quote the annotation (`\"{name}\"`), or put the import in "
            f"`requires:` so it exists at load"
            if read.annotation_only
            else "put the import in `requires:` so it exists at load"
        )
    elif read.cause == "own_name":
        why = (
            f"'{name}' is the class being defined, and its name is bound "
            f"only when the class statement ends"
        )
        fix = (
            f"quote the annotation (`\"{name}\"`)"
            if read.annotation_only
            else f"read '{name}' after the class, because moving it cannot help"
        )
    else:
        why = "the statement that binds it comes later in the file"
        fix = (
            f"move the declaration of '{name}' above this line, or quote the "
            f"annotation (`\"{name}\"`) if the two declarations name each other"
            if read.annotation_only
            else f"move the declaration of '{name}' above this line"
        )
    return why, fix


def unbound_name_findings(
    module: S0maModule,
    python_output: str,
    source_path: Path,
    mode: StrictnessMode,
    *,
    knows_every_target: bool = True,
    requires_python: tuple[str, ...] | None = None,
) -> list[S0maError]:
    """Report each unbound name in one emitted module at its ``.s0ma`` line.

    *requires_python* is the project's declared range. It decides whether
    an annotation read before its binding fails on a Python the project
    supports.

    The emitter adds the privileged imports that ``tests:`` and ``observes:``
    targets rely on only for the modules it can see. Outside a real project
    (a single-file transpile, a file checked with no ``[tool.s0ma]``) a
    target may live in a file it was not given, so a module with tests or
    ganglia cannot be judged and is left alone.
    """
    if not knows_every_target and (module.tests or module.ganglia):
        return []
    reads = find_unbound_names(
        python_output,
        module_name=module.module.name,
        requires_python=requires_python,
    )
    if not reads:
        return []

    source_map = SourceMapGenerator().generate(
        module,
        python_output,
        source_file=str(source_path),
        output_file=f"{module.module.name}.py",
    )
    findings: list[S0maError] = []
    for read in reads:
        location = resolve_output_line(source_map, read.line)
        where = f" in '{location.declaration}'" if location.declaration else ""
        line = location.source_line or 1
        context = {
            "name": read.name,
            "emitted_line": read.line,
            "read_count": read.read_count,
        }
        if read.cause != "unbound":
            why, order_fix = _load_order_text(read)
            pythons = (
                "Python 3.11 to 3.13" if read.annotation_only else "every Python"
            )
            findings.append(S0maError(
                code="UNBOUND_NAME_AT_LOAD",
                message=(
                    f"Module '{module.module.name}' reads '{read.name}'{where} "
                    f"when it loads, before anything has bound it: {why}. "
                    f"Importing the module raises NameError on {pythons}."
                ),
                severity=get_severity("UNBOUND_NAME_AT_LOAD", mode) or "error",
                remediation=(
                    f"To fix it, {order_fix}. The build writes nothing for "
                    f"this module until the read is fixed."
                ),
                file=location.source_file,
                line=line,
                column=0,
                context={**context, "cause": read.cause},
            ))
            continue
        fix = _fix_for(read.name)
        if read.at_load:
            findings.append(S0maError(
                code="UNBOUND_NAME_AT_LOAD",
                message=(
                    f"Module '{module.module.name}' reads '{read.name}'{where} "
                    f"when it loads, and nothing binds that name. Importing "
                    f"the module raises NameError on Python 3.11 to 3.13."
                ),
                severity=get_severity("UNBOUND_NAME_AT_LOAD", mode) or "error",
                remediation=(
                    f"To bind '{read.name}', {fix}. A `def` line counts as "
                    f"body code. The build writes nothing for this module "
                    f"until the name is bound."
                ),
                file=location.source_file,
                line=line,
                column=0,
                context=context,
            ))
        else:
            findings.append(S0maError(
                code="UNBOUND_NAME_IN_BODY",
                message=(
                    f"Module '{module.module.name}' reads '{read.name}'{where} "
                    f"when a body runs, and nothing binds that name. The call "
                    f"raises NameError."
                ),
                severity=get_severity("UNBOUND_NAME_IN_BODY", mode) or "warning",
                remediation=f"To bind '{read.name}', {fix}.",
                file=location.source_file,
                line=line,
                column=0,
                context=context,
            ))
    return findings
