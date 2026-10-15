"""Topological sort of project modules — M10 (feedback 5–6).

Every consumer project pre-M10 hand-maintained a ``MODULE_IMPORT_ORDER``
list in ``bootstrap/startup.py``. The IR already carries the dependency
graph (each module's ``uses:`` edges); M10 surfaces it.

The build emits the topological order under ``topological_import_order``
in ``build.s0ma.json``; the runtime helper
:func:`s0ma.bootstrap.bootstrap_imports` reads that field and imports
modules in dependency order. The hand-maintained list is gone.

Algorithm
---------

Kahn's algorithm with deterministic alphabetical tie-breaking. Nodes are
project module names; an edge ``A → B`` means *A depends on B* (i.e., A
declares ``uses: [B.X]``). The output lists targets first — modules with
no dependencies emit before modules that depend on them, which is the
order ``importlib`` must follow.

Cycle detection
---------------

If Kahn's algorithm cannot drain the graph (some nodes still have
non-zero in-degree after processing every reachable node), the graph
contains a cycle. We surface that as ``MODULE_DEPENDENCY_CYCLE`` (build
error in every strictness mode) — see ``s0ma_dsl.config.SEVERITY_MATRIX``.

Note: the four-phase resolver (``resolver/dependency.py``) already
performs DFS cycle detection during Phase 1 and emits
``CIRCULAR_DEPENDENCY``. In normal flow the resolver fires first, so
``MODULE_DEPENDENCY_CYCLE`` is the topological-sort-path's own
defensive backstop. It also fires when the topological sort is invoked
standalone (e.g., via ``s0ma topo``) without a full resolver pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer

if TYPE_CHECKING:
    from s0ma_dsl.ast_nodes.nodes import S0maModule

__all__ = [
    "ModuleDependencyCycleError",
    "compute_topological_order",
]


def _module_from_qualified(qualified_name: str) -> str:
    """``'routing.select_evaluator'`` → ``'routing'``.

    Mirrors the helper in ``resolver/dependency.py``; duplicated locally
    so this module can be imported without dragging in the four-phase
    resolver. Single-segment names (no dot) are returned as-is, which
    correctly treats them as "no module prefix" (the caller filters
    those out before they become graph edges).
    """
    parts = qualified_name.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else qualified_name


@component(
    name="S0maDSL_ModuleDependencyCycleError",
    kind=ComponentKind.MODEL,
    layer=Layer.FRAMEWORK,
    intent=(
        "Raised by compute_topological_order when the project's uses: "
        "graph contains a cycle, naming the modules in the cycle."
    ),
    idempotent=True,
    is_framework=True,
)
@dataclass(frozen=True)
class ModuleDependencyCycleError(Exception):
    """Raised when the module dependency graph contains a cycle.

    Attributes
    ----------
    cycle_modules:
        The set of module names that participate in the cycle. Sorted
        for diagnostic stability. The error message lists them in
        sorted order so the user can locate the offending ``uses:``
        chain.

    The CLI's ``s0ma topo`` and ``s0ma build`` commands catch this and
    surface it as a ``MODULE_DEPENDENCY_CYCLE`` diagnostic with severity
    ``error`` in every strictness mode (see
    ``s0ma_dsl.config.SEVERITY_MATRIX``).
    """

    cycle_modules: tuple[str, ...]

    def __post_init__(self) -> None:
        # ``Exception.__init__`` populates ``args`` from positional
        # arguments. Frozen dataclasses bypass that, so set the message
        # explicitly so ``str(err)`` reads naturally.
        message = (
            f"Module dependency cycle detected among: "
            f"{', '.join(self.cycle_modules)}. "
            f"Break the cycle by removing one of the uses: entries in "
            f"the chain or by introducing a shared lower-layer module."
        )
        # Bypass frozen dataclass to set the inherited Exception args
        # without making this dataclass mutable. (object.__setattr__ is
        # the standard escape hatch for frozen dataclasses.)
        object.__setattr__(self, "args", (message,))

    def __str__(self) -> str:
        return self.args[0] if self.args else ""


@component(
    name="S0maDSL_compute_topological_order",
    kind=ComponentKind.FUNCTION,
    layer=Layer.FRAMEWORK,
    intent=(
        "Compute the topological order of project modules from their "
        "uses: edges. Deterministic via alphabetical tie-breaking; "
        "raises ModuleDependencyCycleError on cycle."
    ),
    idempotent=True,
    is_framework=True,
)
def compute_topological_order(
    modules: dict[str, S0maModule],
) -> tuple[str, ...]:
    """Return project module names in topological (dependency) order.

    A module ``A`` that declares ``uses: [B.X]`` will appear *after*
    ``B`` in the output — i.e., the order is the order ``importlib``
    must follow to satisfy every ``uses:`` edge before its consumer is
    imported.

    Parameters
    ----------
    modules:
        Mapping of module name to ``S0maModule``. Only modules in the
        mapping become graph nodes; ``uses:`` entries pointing at names
        outside the mapping are ignored (they refer to context-only or
        external modules and do not constrain the import order of the
        in-project set).

    Returns
    -------
    tuple[str, ...]
        Module names in dependency-first order. Stable across runs:
        when multiple nodes have equal in-degree, alphabetical order
        breaks the tie.

    Raises
    ------
    ModuleDependencyCycleError
        When Kahn's algorithm cannot drain the graph — i.e., the
        ``uses:`` edges form a cycle. The exception names every module
        that remains with non-zero in-degree (the cycle members and any
        modules transitively dependent on the cycle).
    """
    # ----- Build adjacency (out-edges) and in-degree map -----
    # An edge from ``A`` to ``B`` means *A depends on B* (A imports B).
    # Kahn's algorithm processes nodes with in-degree zero first; here
    # ``in_degree[X]`` counts how many *consumers* of X remain to be
    # placed. When we want B (a target) to come *before* A (a consumer),
    # the consumer-counting in-degree means modules that nobody imports
    # are emitted first — wrong for our use case.
    #
    # The fix: orient edges so that ``in_degree[X]`` counts how many
    # modules *X depends on*. Then leaf-dependency modules (in_degree
    # zero) come out first, and the order satisfies importlib's
    # requirement to import dependencies before consumers. So we record
    # ``A → B`` as "A depends on B" but increment ``in_degree[A]`` per
    # outgoing edge from A, not ``in_degree[B]``.
    in_degree: dict[str, int] = dict.fromkeys(modules, 0)
    # ``consumers[B]`` lists every A that depends on B. Used to
    # decrement the right counter when B is emitted.
    consumers: dict[str, list[str]] = {name: [] for name in modules}

    for source in sorted(modules):
        s0ma_module = modules[source]
        seen_targets: set[str] = set()
        for use in s0ma_module.module.uses:
            target = _module_from_qualified(use.qualified_name)
            if target == source:
                # Self-import — ignore. The grammar forbids this in
                # general; if one slips through, treating it as a no-op
                # keeps the topological sort robust.
                continue
            if target not in modules:
                # Out-of-project reference (context-only or external).
                # Does not constrain in-project ordering.
                continue
            if target in seen_targets:
                continue
            seen_targets.add(target)
            in_degree[source] += 1
            consumers[target].append(source)

    # ----- Kahn's algorithm with alphabetical tie-breaking -----
    # Maintain ``ready`` as a sorted list of names with in_degree zero.
    # Using ``sorted(...)`` per iteration keeps the algorithm tiny and
    # the determinism explicit; project module counts are O(10s–100s),
    # so the asymptotic cost is irrelevant. The classic heap-based
    # variant is faster but adds a dependency on heapq's stability
    # promises that the explicit sort makes obvious.
    ready = sorted(name for name, deg in in_degree.items() if deg == 0)
    order: list[str] = []

    while ready:
        node = ready.pop(0)
        order.append(node)
        # Decrement every consumer's in-degree; promote any that hit 0.
        for consumer in sorted(consumers[node]):
            in_degree[consumer] -= 1
            if in_degree[consumer] == 0:
                ready.append(consumer)
        ready.sort()

    if len(order) != len(modules):
        # Some nodes still have in-degree > 0 — cycle. Collect every
        # surviving name (sorted) so the error message is stable.
        remaining = tuple(
            sorted(name for name, deg in in_degree.items() if deg > 0)
        )
        raise ModuleDependencyCycleError(cycle_modules=remaining)

    return tuple(order)
