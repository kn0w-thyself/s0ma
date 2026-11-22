"""Find the names an emitted module reads and nothing binds.

``compile()`` does not resolve global names, so a module whose signature
says ``-> dict[str, Any]`` with no ``typing.Any`` in ``requires:`` used to
check clean, build, and raise ``NameError`` on import. This walks the
emitted text, which already holds everything that can bind a name (declared
imports, framework imports, soft-require fallbacks, deferred imports,
privileged imports), and reports each global read that no module-level
binding or builtin covers.

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
``__prepare__``. A name bound anywhere at module level counts as bound,
whatever the order and whatever condition guards it. The bounds and values
of PEP 695 type parameters and aliases are evaluated lazily and are not read.
"""

from __future__ import annotations

import ast
import builtins
import typing
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from s0ma_dsl.codegen.source_map import SourceMapGenerator, resolve_output_line
from s0ma_dsl.config import get_severity
from s0ma_dsl.errors import S0maError

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from s0ma_dsl.ast_nodes.nodes import S0maModule
    from s0ma_dsl.config import StrictnessMode

_ScopeKind = Literal["module", "class", "function", "comprehension", "type_params"]

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


@dataclass(frozen=True)
class UnboundRead:
    """One name nothing binds, at the first place the module reads it."""

    name: str
    line: int
    at_load: bool
    read_count: int = 1


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


def _bind(scope: _Scope, roots: Iterable[ast.AST]) -> None:
    """Add what *roots* bind in *scope*, without entering nested scopes."""
    stack = list(roots)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Name):
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
    if isinstance(node, ast.Subscript):
        target = node.value
        return (
            isinstance(target, ast.Attribute)
            and target.attr == "modules"
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
            and isinstance(node.slice, ast.Name)
            and node.slice.id == "__name__"
        )
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return isinstance(node.value, ast.Name) and node.value.id == "builtins"
    return False


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


def find_unbound_names(python_source: str) -> list[UnboundRead]:
    """Every name *python_source* reads and nothing binds, first read first.

    A name read both at load and in a body is reported once, as a load read:
    that is the failure the module hits first. Text that does not parse
    returns nothing, because the build reports it elsewhere.
    """
    try:
        tree = ast.parse(python_source)
    except (SyntaxError, ValueError, RecursionError):
        return []

    module_scope = _Scope("module", None)
    future_annotations = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            # A declared global is the author saying the module holds it.
            module_scope.bound.update(node.names)
        elif isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            if "*" in names:
                return []
            if node.module == "__future__" and "annotations" in names:
                future_annotations = True
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


def unbound_name_findings(
    module: S0maModule,
    python_output: str,
    source_path: Path,
    mode: StrictnessMode,
    *,
    knows_every_target: bool = True,
) -> list[S0maError]:
    """Report each unbound name in one emitted module at its ``.s0ma`` line.

    The emitter adds the privileged imports that ``tests:`` and ``observes:``
    targets rely on only for the modules it can see. Outside a real project
    (a single-file transpile, a file checked with no ``[tool.s0ma]``) a
    target may live in a file it was not given, so a module with tests or
    ganglia cannot be judged and is left alone.
    """
    if not knows_every_target and (module.tests or module.ganglia):
        return []
    reads = find_unbound_names(python_output)
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
