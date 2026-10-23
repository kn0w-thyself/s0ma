"""The literal value of a CONSTANT cell, read from its body.

A constant whose body assigns a simple literal (``MIN_INTERVAL_SECONDS =
60``) carries that literal through the canonical IR (``fields.value``),
the emitted registration (the ``value=`` argument of
``register_constant``), the registry (``metadata["value"]``) and the
self-context companion, so a self-model answers "what is the floor" with
the number and not only with the sentence an author wrote about it.

The rule is deliberately narrow and the same on every surface. A value
is carried when the cell's body assigns, at top level, to the cell's own
name, and the assigned expression is one of: an ``int``, ``float``,
``str``, ``bool`` or ``None`` literal (a numeric literal may carry a
sign), or a tuple or list of those. Tuples are carried as JSON arrays,
which is how the IR and the companion can hold them, and the registry
gets the same shape so the three agree. Anything else carries no value:
an expression, a name, a dict, a nested sequence, a non-finite float, an
embedded ``content: @file(...)`` body (the file is already recorded by
hash in the build manifest), or a literal whose JSON form is larger than
:data:`CONSTANT_VALUE_MAX_BYTES`. The self-model then says nothing about
the value rather than something partial, because a truncated literal is
a wrong literal.
"""

from __future__ import annotations

import ast
import json
import math
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

from s0ma_dsl.ast_nodes.enums import Kind

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import CellDecl

__all__ = ["CONSTANT_VALUE_MAX_BYTES", "constant_literal"]

#: The largest JSON encoding of a constant's literal that is carried.
#: Limits, thresholds, names and short tuples fit; a prompt template or
#: an embedded page does not, and those are better reached through the
#: module than copied into every artifact that describes it.
CONSTANT_VALUE_MAX_BYTES = 1_024


def _scalar(node: ast.expr) -> tuple[bool, object]:
    """Read one scalar literal node; ``(False, None)`` for anything else."""
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or isinstance(value, (bool, int, str)):
            return True, value
        if isinstance(value, float):
            return math.isfinite(value), value
        return False, None
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
        and not isinstance(node.operand.value, bool)
    ):
        signed = node.operand.value
        if isinstance(node.op, ast.USub):
            signed = -signed
        if isinstance(signed, float) and not math.isfinite(signed):
            return False, None
        return True, signed
    return False, None


def _literal(node: ast.expr) -> tuple[bool, object]:
    """Read a scalar or a flat tuple/list of scalars."""
    found, value = _scalar(node)
    if found:
        return True, value
    if isinstance(node, (ast.Tuple, ast.List)):
        items: list[object] = []
        for element in node.elts:
            found, value = _scalar(element)
            if not found:
                return False, None
            items.append(value)
        return True, items
    return False, None


@component(
    name="S0maDSL_constant_literal",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Reads the simple literal a CONSTANT cell's body assigns to the cell's name, so the "
        "IR, the emitted registration and the self-context carry the constant's value."
    ),
    idempotent=True,
    is_framework=True,
)
def constant_literal(cell: CellDecl) -> tuple[bool, object]:
    """Return ``(True, value)`` when *cell* is a CONSTANT whose body assigns a simple literal.

    The last top-level assignment to the cell's name wins, matching the
    import surface the emitter writes for the cell. See the module
    docstring for what counts as a literal and why the rest is left out.
    """
    if cell.kind != Kind.CONSTANT or cell.embedded_content is not None or not cell.body:
        return False, None
    try:
        tree = ast.parse(cell.body)
    except SyntaxError:
        return False, None

    value_node: ast.expr | None = None
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == cell.name
                for target in statement.targets
            ):
                value_node = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and statement.value is not None
            and isinstance(statement.target, ast.Name)
            and statement.target.id == cell.name
        ):
            value_node = statement.value
    if value_node is None:
        return False, None

    found, value = _literal(value_node)
    if not found:
        return False, None
    encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(encoded) > CONSTANT_VALUE_MAX_BYTES:
        return False, None
    return True, value
