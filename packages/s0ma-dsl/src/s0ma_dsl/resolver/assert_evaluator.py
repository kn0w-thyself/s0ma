"""Narrow AST evaluator for ``doc-guide`` assert expressions.

Implements validation layer 4 of the documentation subsystem (design §8.4):
every assert expression in a ``doc-guide`` is evaluated against the
registry-namespace view of the project. Asserts that evaluate to false
produce an ``ASSERT_FAILED`` diagnostic with an expected-vs-actual diff;
asserts that cannot be evaluated (because a referenced field is missing
or an entity cannot be resolved) produce ``ASSERT_UNEVALUABLE``.

The assert grammar is deliberately narrower than the filter grammar:
supported constructs are entity-rooted field access, ``==``, ``!=``,
``in``, and boolean composition (``and`` / ``or`` / ``not``). This
constraint is structurally enforced by the M2 parser — the evaluator
simply walks the already-parsed AST.

PRD references: FR-29 (diagnostics quality), §2.4 (error system).
Design references: §8.4 assert evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.nodes import (
    AssertBoolean,
    AssertComparison,
    DocGuideDecl,
    SourceLocation,
)
from s0ma_dsl.errors import S0maResolutionError
from s0ma_dsl.resolver.doc_resolver import _FIELDS_BY_KIND, ProjectIndex  # noqa: PLC2701

__all__ = [
    "AssertEvaluator",
    "AssertResult",
]


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssertResult:
    """Outcome of evaluating a single assert expression.

    ``passed`` is True when the expression evaluates to true. When False,
    ``diagnostic`` carries the :class:`S0maResolutionError` describing
    the failure (either ``ASSERT_FAILED`` or ``ASSERT_UNEVALUABLE``).
    """

    passed: bool
    diagnostic: S0maResolutionError | None


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


@component(
    name="S0maDSL_AssertEvaluator",
    kind=ComponentKind.SERVICE,
    layer=Layer.FRAMEWORK,
    intent=(
        "Evaluates doc-guide assert expressions against a project index, emitting ASSERT_FAILED "
        "or ASSERT_UNEVALUABLE diagnostics."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass
class AssertEvaluator:
    """Evaluates assert expressions against a :class:`ProjectIndex`.

    The evaluator is a small interpreter over the narrow assert AST
    shipped by M2. It does not attempt to rewrite or normalise the
    expression; it walks the structured tree and reports a single
    diagnostic per assert (the first failure discovered).
    """

    index: ProjectIndex

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def evaluate(
        self,
        node: AssertComparison | AssertBoolean,
        *,
        filename: str = "<unknown>",
        base_loc: SourceLocation | None = None,
    ) -> AssertResult:
        """Evaluate a single assert expression and return the result."""
        return self._eval(node, filename, base_loc)

    def evaluate_doc_guide(
        self,
        decl: DocGuideDecl,
        *,
        filename: str = "<unknown>",
    ) -> list[S0maResolutionError]:
        """Evaluate every assert on a doc-guide. Returns failure diagnostics."""
        errors: list[S0maResolutionError] = []
        base_loc = decl.location
        for node in decl.asserts:
            result = self._eval(node, filename, base_loc)
            if not result.passed and result.diagnostic is not None:
                errors.append(result.diagnostic)
        return errors

    # -----------------------------------------------------------------------
    # Dispatch
    # -----------------------------------------------------------------------

    def _eval(
        self,
        node: AssertComparison | AssertBoolean,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> AssertResult:
        if isinstance(node, AssertComparison):
            return self._eval_comparison(node, filename, base_loc)
        if isinstance(node, AssertBoolean):
            return self._eval_boolean(node, filename, base_loc)
        # Defensive: an unknown node type is unevaluable.
        return AssertResult(
            passed=False,
            diagnostic=_unevaluable(
                f"Unknown assert node type {type(node).__name__}",
                remediation="Report this as a transpiler bug.",
                filename=filename,
                loc=base_loc,
                context={"node_type": type(node).__name__},
            ),
        )

    def _eval_boolean(
        self,
        node: AssertBoolean,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> AssertResult:
        op = node.operator
        if op == "not":
            # Parser guarantees exactly one operand for "not".
            inner = self._eval(node.operands[0], filename, base_loc)
            if inner.diagnostic is not None and inner.diagnostic.code == "ASSERT_UNEVALUABLE":
                # Unevaluable propagates — cannot negate what we cannot read.
                return inner
            if inner.passed:
                # The inner comparison held; negating it yields false.
                return AssertResult(
                    passed=False,
                    diagnostic=_failed(
                        "not",
                        inner.diagnostic.context if inner.diagnostic else {},
                        filename=filename,
                        loc=_loc_of(node, base_loc),
                        expected_repr="false (NOT inner)",
                        actual_repr="true (inner held)",
                    ),
                )
            return AssertResult(passed=True, diagnostic=None)

        if op == "and":
            # Short-circuit on the first failure so the diagnostic points
            # at the specific sub-assert the author wrote.
            for sub in node.operands:
                r = self._eval(sub, filename, base_loc)
                if not r.passed:
                    return r
            return AssertResult(passed=True, diagnostic=None)

        if op == "or":
            # All sub-asserts failed or were unevaluable; emit the first
            # failure diagnostic (parser orders operands left-to-right).
            last: AssertResult | None = None
            for sub in node.operands:
                r = self._eval(sub, filename, base_loc)
                if r.passed:
                    return r
                last = r
            # At this point ``last`` cannot be None — parser guarantees
            # at least one operand — but be defensive.
            if last is None:
                return AssertResult(
                    passed=False,
                    diagnostic=_failed(
                        "or",
                        {},
                        filename=filename,
                        loc=_loc_of(node, base_loc),
                        expected_repr="any operand true",
                        actual_repr="no operands",
                    ),
                )
            return last

        # Unknown boolean operator — treat as transpiler bug.
        return AssertResult(
            passed=False,
            diagnostic=_unevaluable(
                f"Unknown boolean operator '{op}' in assert expression.",
                remediation=(
                    "Rewrite the assert using only 'and', 'or', or 'not'; "
                    "if this message persists report it as a transpiler bug."
                ),
                filename=filename,
                loc=_loc_of(node, base_loc),
                context={"operator": op},
            ),
        )

    def _eval_comparison(
        self,
        node: AssertComparison,
        filename: str,
        base_loc: SourceLocation | None,
    ) -> AssertResult:
        ref = node.lhs
        loc = _loc_of(node, ref.location or base_loc)

        # 1. Resolve the entity.
        ent = self.index.lookup(ref.kind, ref.name)
        if ent is None:
            return AssertResult(
                passed=False,
                diagnostic=_unevaluable(
                    f"Assert lhs {ref.kind}::{ref.name} does not resolve "
                    f"to any registered entity.",
                    remediation=(
                        f"Register a {ref.kind} named '{ref.name}' in the "
                        f"project, or correct the reference."
                    ),
                    filename=filename,
                    loc=loc,
                    context={
                        "kind": ref.kind,
                        "name": ref.name,
                        "raw": ref.raw,
                    },
                ),
            )

        # 2. Read the field path. Asserts always target a field (the grammar
        # requires non-empty field_path on AssertComparison.lhs).
        if not ref.field_path:
            return AssertResult(
                passed=False,
                diagnostic=_unevaluable(
                    f"Assert lhs {ref.kind}::{ref.name} has no field path; "
                    f"asserts must compare a specific field.",
                    remediation=(
                        f"Append a field to the reference, e.g. "
                        f"{ref.kind}::{ref.name}.visibility == PUBLIC."
                    ),
                    filename=filename,
                    loc=loc,
                    context={"kind": ref.kind, "name": ref.name},
                ),
            )
        value, field_err = _read_field(ent, ref.field_path, filename, loc)
        if field_err is not None:
            return AssertResult(passed=False, diagnostic=field_err)

        # 3. Compare.
        op = node.operator
        rhs = node.rhs
        if op == "==":
            # ==/!= literals are always a single string (the grammar
            # reserves tuple RHS for ``in``, handled below).
            passed = _compare_equal(value, cast("str", rhs))
        elif op == "!=":
            passed = not _compare_equal(value, cast("str", rhs))
        elif op == "in":
            # ``in`` takes a tuple of literal strings and tests containment.
            options = rhs if isinstance(rhs, tuple) else (rhs,)
            passed = any(_compare_equal(value, opt) for opt in options)
        else:
            return AssertResult(
                passed=False,
                diagnostic=_unevaluable(
                    f"Unknown comparison operator '{op}' in assert.",
                    remediation="Use one of '==', '!=', or 'in'.",
                    filename=filename,
                    loc=loc,
                    context={"operator": op},
                ),
            )

        if passed:
            return AssertResult(passed=True, diagnostic=None)

        return AssertResult(
            passed=False,
            diagnostic=_failed(
                op,
                {
                    "lhs_entity": f"{ref.kind}::{ref.name}",
                    "lhs_field_path": list(ref.field_path),
                    "expected": _readable_rhs(rhs, op),
                    "actual": _readable_value(value),
                    "raw_lhs": ref.raw,
                },
                filename=filename,
                loc=loc,
                expected_repr=_readable_rhs(rhs, op),
                actual_repr=_readable_value(value),
            ),
        )


# ---------------------------------------------------------------------------
# Field reading
# ---------------------------------------------------------------------------


def _read_field(
    ent: Any,
    path: tuple[str, ...],
    filename: str,
    loc: SourceLocation | None,
) -> tuple[Any, S0maResolutionError | None]:
    """Read a dotted field path off an indexed entity's ``fields`` dict."""
    first = path[0]
    if first not in _FIELDS_BY_KIND.get(ent.kind, frozenset()):
        known = sorted(_FIELDS_BY_KIND.get(ent.kind, frozenset()))
        return None, _unevaluable(
            f"Entity {ent.kind}::{ent.name} has no field '{first}'.",
            remediation=f"Use one of {known}, or correct the field name.",
            filename=filename,
            loc=loc,
            context={
                "kind": ent.kind,
                "name": ent.name,
                "field": first,
                "known_fields": known,
            },
        )

    current = ent.fields.get(first)
    for segment in path[1:]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        return None, _unevaluable(
            f"Field path {'.'.join(path)} on {ent.kind}::{ent.name} cannot "
            f"read segment '{segment}'.",
            remediation=(
                f"Field '{first}' is not a nested structure with key "
                f"'{segment}'. V1 asserts only read top-level fields."
            ),
            filename=filename,
            loc=loc,
            context={
                "kind": ent.kind,
                "name": ent.name,
                "field_path": list(path),
                "failed_at": segment,
            },
        )
    return current, None


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------


def _compare_equal(lhs: Any, rhs: str) -> bool:
    """Compare a field value against an assert literal (always a string).

    Literals in the assert grammar are bare identifiers (``PUBLIC``,
    ``DOMAIN``) or quoted strings. Both arrive here as ``str``. Field
    values are normalised to strings when sourced from enums (see
    ``_enum_to_str`` in :mod:`s0ma_dsl.resolver.doc_resolver`); numeric
    fields arrive as their Python values and are compared via string
    coercion so ``latency_ms == 100`` behaves as authors expect.
    """
    if isinstance(lhs, str):
        return lhs == rhs
    if isinstance(lhs, bool):
        # Bool check must precede int check — bool is a subclass of int.
        return str(lhs).lower() == rhs.lower()
    if isinstance(lhs, (int, float)):
        return str(lhs) == rhs
    if isinstance(lhs, (tuple, list)):
        # A bare ``raises == X`` matches if X is an element of the list.
        # Equality with the whole list is intentionally not supported —
        # authors use ``in`` for tuple-side checks.
        return rhs in (_readable_value(v) for v in lhs)
    if lhs is None:
        return rhs in ("", "None", "null")
    # Fallback — coerce both sides to string.
    return str(lhs) == rhs


def _readable_value(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(_readable_value(v) for v in value) + "]"
    if value is None:
        return "None"
    return str(value)


def _readable_rhs(rhs: str | tuple[str, ...], operator: str) -> str:
    if operator == "in" and isinstance(rhs, tuple):
        return "[" + ", ".join(rhs) + "]"
    if isinstance(rhs, tuple):
        return "[" + ", ".join(rhs) + "]"
    return rhs


# ---------------------------------------------------------------------------
# Diagnostic constructors
# ---------------------------------------------------------------------------


def _failed(
    operator: str,
    context: dict[str, Any],
    *,
    filename: str,
    loc: SourceLocation | None,
    expected_repr: str,
    actual_repr: str,
) -> S0maResolutionError:
    return S0maResolutionError(
        code="ASSERT_FAILED",
        message=(
            f"Assert failed ({operator}): expected {expected_repr}, "
            f"got {actual_repr}."
        ),
        file=filename,
        line=_line(loc),
        column=_col(loc),
        severity="error",
        remediation=(
            "Either update the component so the assert holds, or update the "
            "assert to reflect the component's actual state. Asserts are "
            "load-bearing — a false assert means the doc-guide's claims "
            "about the self-model are wrong."
        ),
        context={"operator": operator, **context},
    )


def _unevaluable(
    message: str,
    *,
    remediation: str,
    filename: str,
    loc: SourceLocation | None,
    context: dict[str, Any],
) -> S0maResolutionError:
    return S0maResolutionError(
        code="ASSERT_UNEVALUABLE",
        message=message,
        file=filename,
        line=_line(loc),
        column=_col(loc),
        severity="error",
        remediation=remediation,
        context=context,
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _line(loc: SourceLocation | None) -> int:
    return loc.start_line if loc else 0


def _col(loc: SourceLocation | None) -> int:
    return loc.start_column if loc else 0


def _loc_of(
    node: AssertComparison | AssertBoolean,
    fallback: SourceLocation | None,
) -> SourceLocation | None:
    loc = getattr(node, "location", None)
    return loc or fallback
