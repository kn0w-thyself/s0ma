"""Forward-compatibility detection for 3.12-only Python grammar.

M-12 (POST-8, 0.16.0): when a project declares
``[project].requires-python = ">=3.11"`` (or any range that still
includes 3.11), bodies that author 3.12-only grammar would compile
cleanly under the transpiler's 3.12 ``ast.parse`` but fail at import
time on a 3.11 interpreter. This module walks the body AST and flags
the three known 3.12-only construct families:

1. **Nested-quote f-strings (PEP 701)** — ``f"outer {f"inner"}"``
   works in 3.12+ but not 3.11. The 3.12 PEG grammar drops the
   restriction that f-string expressions cannot contain the same
   quote character as the outer string. AST-level signal: an
   inner ``JoinedStr`` (or ``Constant(str)``) inside a
   ``FormattedValue`` whose ``StrDelta`` quote-character history
   would have produced the conflict pre-3.12. We use a simple
   text-level heuristic against the canonical body source rather
   than walking the AST for this one because the AST does not
   preserve quote-style; the inner-f-string sub-walk catches
   nested ``JoinedStr`` in ``FormattedValue`` bodies which is
   itself a 3.12-only shape.
2. **Walrus-in-comprehension (PEP 572 + 3.12 relaxation)** —
   3.10 / 3.11 tightened named-expression placement inside
   comprehensions; 3.12 re-opened the surface broadly. The
   conservative pattern we flag is ``NamedExpr`` appearing
   anywhere inside a comprehension generator or element — bodies
   that fall back to the older form (``y = expr; ... y ...``)
   are unaffected.
3. **PEP 695 type-parameter syntax** — ``def foo[T](x: T) -> T: ...``,
   ``class Foo[T]: ...``, ``type Vector = list[T]``. The 3.12 AST
   adds a ``type_params`` slot on ``FunctionDef`` / ``AsyncFunctionDef``
   / ``ClassDef``; a non-empty value is the signal. The
   ``ast.TypeAlias`` node is itself 3.12-only.

The detector is intentionally text-based for nested-quote f-strings
(AST does not preserve quote-style) and AST-based for the other two
families. False positives are worse than false negatives — every
flagger here returns a precise, structured location so the validator
can surface it with the body's actual line number.

The version-range check is conservative: the caller only invokes
this module's ``flag_python_312_only`` helper when the project's
``requires_python`` range explicitly includes 3.11. A project pinned
``>=3.12`` (or higher) has opted in and the check stays silent.

PRD references: feedback-5.5 (POST-8), this milestone is M-12 in
``post-phase2_implementation_plan.md``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from s0ma.decorators import component
from s0ma.types import ComponentKind
from s0ma.types import Layer as S0maLayer

__all__ = [
    "Python312OnlyFinding",
    "flag_python_312_only",
    "requires_python_includes_311",
]


# ---------------------------------------------------------------------------
# Finding shape
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_Python312OnlyFinding",
    kind=ComponentKind.MODEL,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Structured record of a 3.12-only Python grammar construct detected in an emitted body."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class Python312OnlyFinding:
    """A single 3.12-only grammar construct detected in a body.

    Attributes
    ----------
    kind:
        Short stable identifier for the construct family. One of:
        ``"nested_quote_fstring"``, ``"walrus_in_comprehension"``,
        ``"pep_695_type_params"``, ``"pep_695_type_alias"``. The
        validator uses this as the diagnostic's ``context.kind`` so
        downstream tooling can switch on it.
    description:
        Human-readable description of the construct. Surfaces in the
        diagnostic message.
    line:
        Line number relative to the body (1-based). The validator
        adds the body's offset within the source to produce the
        canonical line number.
    column:
        Column offset (0-based).
    """

    kind: str
    description: str
    line: int
    column: int


# ---------------------------------------------------------------------------
# Version-range predicate
# ---------------------------------------------------------------------------


# Match a PEP 440 specifier clause like ``>=3.11``, ``<3.13``, ``~=3.12``
# and capture the operator + the dotted version.
_SPECIFIER_RE = re.compile(
    r"^\s*(==|!=|<=|>=|<|>|~=)\s*(\d+(?:\.\d+(?:\.\d+(?:\.\d+)?)?)?)"
)


def _parse_version_clause(clause: str) -> tuple[str, tuple[int, ...]] | None:
    """Return ``(op, version_tuple)`` for a single specifier clause, or ``None``.

    The dotted version is parsed into a tuple of ints. Trailing
    ``.*`` wildcards are stripped (``3.11.*`` → ``(3, 11)``). Unknown
    operators or non-numeric versions return ``None`` — the caller
    treats unparseable clauses conservatively (assume the project
    might still include 3.11).
    """
    m = _SPECIFIER_RE.match(clause)
    if not m:
        return None
    op = m.group(1)
    raw_version = m.group(2)
    # Strip trailing ``.*`` if the regex would still allow it (we don't,
    # but defensive).
    raw_version = raw_version.rstrip(".*")
    try:
        version = tuple(int(p) for p in raw_version.split("."))
    except ValueError:
        return None
    return op, version


def _version_includes_311(op: str, version: tuple[int, ...]) -> bool:
    """Return ``True`` iff a single clause permits Python 3.11.

    The clause is interpreted against the candidate version 3.11
    (specifically 3.11.0 for boundary semantics). Returns ``True``
    when 3.11 satisfies the clause, ``False`` when it does not.

    The supported operators are the PEP 440 set used in practice for
    ``requires-python``: ``>=``, ``>``, ``<=``, ``<``, ``==``,
    ``!=``, ``~=``.

    Unknown operators conservatively return ``True`` (assume the
    clause does not exclude 3.11).
    """
    target = (3, 11)
    # Normalise to a fixed-length comparison: pad both with zeros to
    # match the longer tuple. ``(3, 11) >= (3,)`` should still
    # compute correctly because tuple comparison is lex.
    if op == ">=":
        return target >= version
    if op == ">":
        return target > version
    if op == "<=":
        return target <= version
    if op == "<":
        return target < version
    if op == "==":
        # Special case: ``==3.11.x`` (any x) is satisfied; ``==3.12``
        # is not. Compare only on the shared prefix length.
        n = min(len(target), len(version))
        return target[:n] == version[:n]
    if op == "!=":
        n = min(len(target), len(version))
        return target[:n] != version[:n]
    if op == "~=":
        # PEP 440 compatible-release: ``~=3.11`` means
        # ``>=3.11, <4``; ``~=3.11.5`` means ``>=3.11.5, <3.12``.
        # For our 3.11 inclusion question, ``~=`` permits 3.11 iff
        # the floor is ≤ 3.11 AND the implied ceiling is > 3.11.
        # We compute both endpoints conservatively.
        if not version:
            return True
        if target < version:
            # Floor higher than 3.11 — does not include it.
            return False
        # Implied ceiling: bump the second-to-last component by 1
        # and zero the rest. ``~=3.11`` → ceiling ``4.0``. ``~=3.12``
        # → ceiling ``4.0`` (still excludes 3.11 because the floor
        # is higher than target). ``~=3.11.5`` → ceiling ``3.12``.
        if len(version) == 1:
            # Permit anything ``>= X.0``; 3.11 included iff version ≤ 3.
            return version[0] <= target[0]
        # Strict less-than the bumped second-to-last component.
        head = version[:-1]
        ceiling = head[:-1] + (head[-1] + 1,)
        return target < ceiling
    # Unknown operator — conservative.
    return True


@component(
    name="S0maDSL_requires_python_includes_311",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Predicate: does the project's [project].requires-python range include Python 3.11?"
    ),
    idempotent=True,
    is_framework=True,
)
def requires_python_includes_311(
    requires_python: tuple[str, ...] | None,
) -> bool:
    """Return ``True`` iff the project's declared range includes Python 3.11.

    M-12 (POST-8, 0.16.0): the version-range check is the trigger
    gate for the ``PARSE_GRAMMAR_FORWARD_INCOMPAT`` pass. The pass
    only fires when this predicate returns ``True``.

    Decision shapes:

    * ``None`` (no ``requires-python``) → ``False``. The project
      has declared no Python floor; the check stays silent under
      the conservative default ("we don't know what 3.x the
      consumer targets, so don't pretend to enforce 3.11
      portability").
    * ``(">=3.11",)`` → ``True``. The range explicitly admits 3.11.
    * ``(">=3.11", "<3.13")`` → ``True``. Both clauses permit 3.11.
    * ``(">=3.12",)`` → ``False``. The project has opted in to
      3.12+ grammar; the check would be noise.
    * ``(">=3.13",)`` → ``False``. Higher floor; same rationale.
    * Unparseable clauses → ``True``. Conservative: if we cannot
      tell, assume the project might still need 3.11 portability
      and fire the check.

    Every clause in the range must be satisfied by 3.11; if any
    clause excludes 3.11, the range does not include it.
    """
    if not requires_python:
        return False
    for clause in requires_python:
        parsed = _parse_version_clause(clause)
        if parsed is None:
            # Conservative: an unparseable clause does not let us
            # rule out 3.11; treat it as "might include 3.11" so
            # the check still fires.
            continue
        op, version = parsed
        if not _version_includes_311(op, version):
            return False
    return True


# ---------------------------------------------------------------------------
# Body-level detector
# ---------------------------------------------------------------------------


# Matches an f-string opener (``f"``, ``f'``, ``F"``, etc.) and
# captures the quote character so we can scan the rest of the body
# for the same quote inside an embedded brace expression.
_FSTRING_OPENER_RE = re.compile(r"""(?P<prefix>[fF])(?P<quote>"{3}|'{3}|"|')""")


def _scan_nested_quote_fstrings(body: str) -> list[Python312OnlyFinding]:
    """Detect nested-quote f-strings (PEP 701, 3.12-only).

    The AST does not preserve quote-style on string literals, so we
    fall back to a text scan. The conservative pattern: an f-string
    opener whose body (up to its matching closing quote) contains
    a brace-expression whose contents contain another instance of
    the *same* quote character. Pre-PEP-701 this was a syntax error;
    PEP 701 (3.12) lifts the restriction.

    The scan is line-based and conservative. False negatives are
    acceptable (rare edge case grammar nesting); false positives
    would erode author trust.

    The walker handles:

    * Single-line f-strings: ``f"... {f"inner"} ..."``
    * Same-quote nesting only (the rule). Mixed-quote nesting
      (``f"... {f'inner'} ..."``) is valid in every modern Python
      version and is NOT flagged.

    Returns a list of findings, one per detected occurrence.
    """
    findings: list[Python312OnlyFinding] = []
    lines = body.splitlines()
    for line_idx, line in enumerate(lines):
        pos = 0
        while pos < len(line):
            m = _FSTRING_OPENER_RE.search(line, pos)
            if not m:
                break
            quote = m.group("quote")
            opener_end = m.end()
            # Walk the f-string body, tracking brace depth. The
            # f-string ends when we hit the matching quote sequence
            # at brace_depth == 0.
            brace_depth = 0
            i = opener_end
            same_quote_in_braces = False
            while i < len(line):
                ch = line[i]
                if ch == "\\" and i + 1 < len(line):
                    # Skip escape sequences (incl. \\" inside the body).
                    i += 2
                    continue
                if brace_depth == 0 and line.startswith(quote, i):
                    # End of the f-string.
                    i += len(quote)
                    break
                if ch == "{":
                    if line[i:i + 2] == "{{":
                        # Literal ``{{`` escape — not a brace expr.
                        i += 2
                        continue
                    brace_depth += 1
                    i += 1
                    continue
                if ch == "}":
                    if line[i:i + 2] == "}}":
                        # Literal ``}}`` escape.
                        i += 2
                        continue
                    if brace_depth > 0:
                        brace_depth -= 1
                    i += 1
                    continue
                if brace_depth > 0 and line.startswith(quote, i):
                    # Same quote char nested inside a brace
                    # expression — the 3.12-only signal.
                    same_quote_in_braces = True
                    i += len(quote)
                    continue
                i += 1
            if same_quote_in_braces:
                findings.append(Python312OnlyFinding(
                    kind="nested_quote_fstring",
                    description=(
                        f"Nested-quote f-string (the same {quote!r} quote "
                        f"character appears inside a brace expression). "
                        f"PEP 701 lifted this restriction in Python 3.12; "
                        f"earlier 3.x versions raise SyntaxError at import."
                    ),
                    line=line_idx + 1,
                    column=m.start(),
                ))
            pos = max(i, opener_end + 1)
    return findings


def _scan_ast(tree: ast.AST) -> list[Python312OnlyFinding]:
    """Walk an AST and flag walrus-in-comprehension + PEP 695 syntax.

    M-12 (POST-8, 0.16.0). The walker is one pass over ``ast.walk``;
    each construct family adds its own ``Python312OnlyFinding``.

    Walrus-in-comprehension:
        Any ``NamedExpr`` (the ``:=`` operator) appearing inside the
        ``generators`` or element of a ``ListComp`` / ``SetComp`` /
        ``DictComp`` / ``GeneratorExp``. 3.10–3.11 tightened the
        placement rules; 3.12 reopened them broadly. We flag every
        named-expression in a comprehension context; false positives
        on bodies that happen to compile fine on 3.11 are accepted
        (the remediation is the same — extract the assignment to
        the outer scope).

    PEP 695 type parameter syntax:
        ``FunctionDef`` / ``AsyncFunctionDef`` / ``ClassDef`` with a
        non-empty ``type_params`` field, OR an ``ast.TypeAlias``
        node anywhere in the tree (the ``type Foo = ...`` statement
        is 3.12-only).
    """
    findings: list[Python312OnlyFinding] = []

    # Track comprehension nesting so a NamedExpr inside one fires.
    comprehension_classes = (
        ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    )

    def _walk_for_walrus(
        node: ast.AST, in_comprehension: bool,
    ) -> None:
        if isinstance(node, comprehension_classes):
            in_comprehension = True
        if (
            isinstance(node, ast.NamedExpr)
            and in_comprehension
        ):
            findings.append(Python312OnlyFinding(
                kind="walrus_in_comprehension",
                description=(
                    "Walrus operator (`:=`) inside a comprehension. "
                    "Python 3.10/3.11 tightened the placement rules; "
                    "Python 3.12 (PEP 572 follow-up) reopened them. "
                    "On 3.11 the comprehension form raises "
                    "SyntaxError at import."
                ),
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
            ))
        for child in ast.iter_child_nodes(node):
            _walk_for_walrus(child, in_comprehension)

    _walk_for_walrus(tree, in_comprehension=False)

    for node in ast.walk(tree):
        # PEP 695 type-params on def / async def / class.
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            type_params = getattr(node, "type_params", None)
            if type_params:
                findings.append(Python312OnlyFinding(
                    kind="pep_695_type_params",
                    description=(
                        f"PEP 695 type-parameter syntax on "
                        f"{type(node).__name__} '{node.name}' "
                        f"(`{node.name}[T]: ...`). Introduced in "
                        f"Python 3.12; 3.11 raises SyntaxError at import. "
                        f"Use `TypeVar` from `typing` for 3.11 portability."
                    ),
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0),
                ))
        # PEP 695 `type Foo = ...` statement.
        type_alias_cls = getattr(ast, "TypeAlias", None)
        if type_alias_cls is not None and isinstance(node, type_alias_cls):
            name_node = getattr(node, "name", None)
            alias_name = getattr(name_node, "id", "<unknown>")
            findings.append(Python312OnlyFinding(
                kind="pep_695_type_alias",
                description=(
                    f"PEP 695 `type {alias_name} = ...` statement. "
                    f"Introduced in Python 3.12; 3.11 raises "
                    f"SyntaxError at import. Use `TypeAlias` from "
                    f"`typing` for 3.11 portability."
                ),
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
            ))

    # Stable ordering for deterministic diagnostics: by (line, column, kind).
    findings.sort(key=lambda f: (f.line, f.column, f.kind))
    return findings


@component(
    name="S0maDSL_flag_python_312_only",
    kind=ComponentKind.FUNCTION,
    layer=S0maLayer.FRAMEWORK,
    intent=(
        "Walk a body's source / AST and flag every 3.12-only Python grammar construct."
    ),
    idempotent=True,
    is_framework=True,
)
def flag_python_312_only(body: str) -> list[Python312OnlyFinding]:
    """Return every 3.12-only grammar finding in *body*.

    M-12 (POST-8, 0.16.0). Combines the text-based scan for
    nested-quote f-strings (the AST does not preserve quote-style)
    with the AST walk for walrus-in-comprehension and PEP 695
    constructs. Findings are returned in source order ``(line,
    column, kind)``.

    Body parsing falls back gracefully: if ``ast.parse`` raises
    ``SyntaxError``, the AST walk returns an empty list. The
    text-based nested-quote scan still runs (it never raises).
    The caller's outer ``PARSE_ERROR`` pass handles the syntax
    error; this pass intentionally stays silent so two diagnostics
    do not fire for the same root cause.

    The empty-body case returns an empty list (no findings).
    """
    if not body:
        return []
    findings: list[Python312OnlyFinding] = []
    findings.extend(_scan_nested_quote_fstrings(body))
    try:
        tree = ast.parse(body)
    except SyntaxError:
        # Outer PARSE_ERROR handles this; stay silent here so we
        # don't double-report the same root cause.
        pass
    else:
        findings.extend(_scan_ast(tree))
    findings.sort(key=lambda f: (f.line, f.column, f.kind))
    return findings
