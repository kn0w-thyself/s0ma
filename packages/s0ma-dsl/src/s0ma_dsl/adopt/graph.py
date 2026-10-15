"""The project's own import graph — rung 0's evidence for *what to convert first*.

A retrofit is done leaf-first: convert a module only after everything it
imports at load time has already been converted, or the half-converted
tree stops importing. This module turns the per-file census into that
order, plus the facts a person needs to argue with it — which modules
import which, which knots have to be untied by hand, and which modules
everything else leans on.

Two public functions, and the split between them matters
--------------------------------------------------------

:func:`classify_imports` answers "where does each import come from?".
It returns **new** :class:`~s0ma_dsl.adopt.model.ModuleCensus` records
with every :class:`~s0ma_dsl.adopt.model.ImportFact` ``origin`` resolved
to ``"stdlib"``, ``"first_party"``, ``"third_party"`` or
``"unresolved"``. The census records are frozen, so re-classifying in
place is not an option; a new tuple is the only honest shape. Input
order is preserved, and a census whose imports do not change is passed
through unchanged.

:func:`build_graph` answers "in what order do I convert them?" and
returns :class:`~s0ma_dsl.adopt.model.GraphFacts`. It calls
:func:`classify_imports` itself, so a caller that only wants the graph
needs nothing else.

**B3 (proposals) and B4 (the scan report) call**
:func:`classify_imports` **first and pass the returned censuses on**, so
the report they print carries resolved origins rather than the
placeholder ``"unresolved"`` the census reader left behind.
Classification is idempotent: running it twice gives the same answer,
and it never trusts the incoming ``origin`` — B1 sets what it can and
leaves the rest, so B2 works the question out from scratch every time.

Nothing here reads a file, imports the scanned project, or writes
anything (retrofit rules R-1 and R-2). The input is data; so is the
output.

How an import is resolved
-------------------------

First-party means "a module this project discovered", matched by
**longest dotted prefix** against the set of discovered module names:

* ``import a.b.c`` → ``a.b.c`` if that is a discovered module, else
  ``a.b``, else ``a``, else not first-party.
* ``from a.b import c`` → ``a.b.c`` if that is a discovered module
  (importing a submodule), else ``a.b``, else ``a``. One candidate per
  bound name, so ``from a.b import sub, helper`` where ``sub`` is a
  module and ``helper`` is a function reaches both ``a.b.sub`` and
  ``a.b`` — which is what actually happens at import time.
* A package resolves to the package name itself: discovery names an
  ``__init__.py`` after its package, so ``a.b`` is in the module set
  when ``a/b/__init__.py`` exists and the prefix match finds it with no
  special case.

One thing the graph deliberately does **not** model: the implicit
parent-package import. Python really does run ``pkg/__init__.py`` before
``pkg/models.py``, but a package whose ``__init__.py`` re-exports from
its own modules — the ordinary, correct shape — would then be one giant
cycle covering every module in it, and a conversion order that says
"these forty modules convert as one piece" tells nobody anything. Only
imports somebody actually wrote become edges. The ``__init__.py`` sorts
late on its own re-export edges, which is where it belongs anyway.

Then, in this order:

1. An import whose target is still a **relative form** — an empty
   string, or a name starting with ``.``, meaning it climbed above the
   top package and B1 could not make it absolute — is ``"unresolved"``.
   Nothing is guessed about it and it contributes no edge.
2. Anything that resolves first-party is ``"first_party"``. First-party
   is checked **before** stdlib on purpose: a flat project with its own
   ``types.py`` really does shadow the standard library, and the
   conversion order has to know that.
3. Otherwise, the first dotted segment against
   :data:`sys.stdlib_module_names` decides ``"stdlib"``. That frozenset
   is the same on every platform (it carries ``winreg`` and ``posix``
   alike), so a scan classifies identically on macOS, Linux and Windows.
4. Everything left is ``"third_party"``.

What is in the graph, and what is not
-------------------------------------

* Only first-party edges. Stdlib and third-party targets never move, so
  they cannot constrain the order.
* **Test files are not in the graph at all** — no node, no edge in
  either direction. A test suite imports everything, so leaving tests in
  would make every application module look depended-upon and flatten the
  order into noise. Their imports are still classified: a census is a
  record of the file, and B4 reports on test files too.
* ``edges`` are load-time imports. ``deferred_edges`` carry the
  function-scoped ones *and* the ``if TYPE_CHECKING:`` ones: neither runs
  when the module is loaded, and both are the escape hatch a working
  import cycle is usually hiding behind. A module that imports another
  both at the top and inside a function appears in both tuples, which is
  the truth about it.
* Self-edges are dropped — a module importing itself constrains nothing.

The order
---------

Cycles are found with Tarjan's strongly-connected-components algorithm,
written **iteratively**: a two-thousand-module chain is a realistic
monorepo and must not meet the recursion limit. Nodes and neighbours are
walked in sorted order, so the components come out the same way every
run.

``order`` is then a leaf-first pass over the condensation (Kahn's
algorithm with an alphabetical tie-break, the same semantics as the
house's :func:`s0ma_dsl.resolver.compute_topological_order`, which this
cannot reuse because that one *raises* on a cycle and a scan must report
one instead). A module appears after everything it imports at load time;
the members of one cycle are adjacent and alphabetical, because nothing
can break that tie honestly; independent components are ordered by their
alphabetically first member.
"""

from __future__ import annotations

import heapq
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.model import GraphFacts

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from s0ma_dsl.adopt.model import ImportFact, ModuleCensus

__all__ = [
    "ORIGIN_FIRST_PARTY",
    "ORIGIN_STDLIB",
    "ORIGIN_THIRD_PARTY",
    "ORIGIN_UNRESOLVED",
    "build_graph",
    "classify_imports",
]


# ---------------------------------------------------------------------------
# The four origins
#
# Named once here so the scanner, the proposals and the report all spell
# them the same way. The strings themselves are part of the
# ``s0ma-adopt-scan@1`` contract (they are dumped into the JSON report),
# so they are values to be reused, never re-typed.
# ---------------------------------------------------------------------------

ORIGIN_STDLIB = "stdlib"
"""The import target ships with Python itself."""

ORIGIN_FIRST_PARTY = "first_party"
"""The import target is another module this project discovered."""

ORIGIN_THIRD_PARTY = "third_party"
"""The import target is an installed dependency."""

ORIGIN_UNRESOLVED = "unresolved"
"""The import target could not be named — a relative import that climbed
above the top package, which nothing static can follow."""


_TEST_ROLE = "test"
"""The :attr:`~s0ma_dsl.adopt.model.SourceFile.role` kept out of the graph."""


# ---------------------------------------------------------------------------
# Resolving one import
# ---------------------------------------------------------------------------


def _is_unresolvable_relative(module: str) -> bool:
    """True when a target is still a relative form B1 could not make absolute.

    The census resolves ``from . import x`` against the module's own
    package before it records anything, so a leading dot (or an empty
    name) that survives means the import climbed above the top package.
    That is the one case the plan leaves as ``"unresolved"``.
    """
    return not module or module.startswith(".")


def _resolve_first_party(candidate: str, modules: frozenset[str]) -> str | None:
    """The longest dotted prefix of *candidate* that is a discovered module.

    ``"a.b.c"`` against ``{"a", "a.b"}`` gives ``"a.b"``. ``None`` when no
    prefix matches, which is what makes the import somebody else's.
    """
    parts = candidate.split(".")
    for cut in range(len(parts), 0, -1):
        prefix = ".".join(parts[:cut])
        if prefix in modules:
            return prefix
    return None


def _import_targets(record: ImportFact, modules: frozenset[str]) -> tuple[str, ...]:
    """Every first-party module one import statement reaches, sorted and deduped.

    One candidate per bound name for a ``from X import a, b``, and the
    bare target for a plain ``import X`` (which binds no names in the
    census). Empty when the statement reaches nothing of ours.
    """
    if _is_unresolvable_relative(record.module):
        return ()
    if record.names:
        candidates = tuple(f"{record.module}.{name}" for name in record.names)
    else:
        candidates = (record.module,)
    found: set[str] = set()
    for candidate in candidates:
        target = _resolve_first_party(candidate, modules)
        if target is not None:
            found.add(target)
    return tuple(sorted(found))


def _origin_of(record: ImportFact, modules: frozenset[str]) -> str:
    """Which of the four origins one import has, worked out from scratch.

    The incoming ``origin`` is deliberately ignored: the census leaves
    what it cannot decide as ``"unresolved"``, so trusting it would let a
    placeholder through as an answer.
    """
    if _is_unresolvable_relative(record.module):
        return ORIGIN_UNRESOLVED
    if _import_targets(record, modules):
        return ORIGIN_FIRST_PARTY
    if record.module.split(".", 1)[0] in sys.stdlib_module_names:
        return ORIGIN_STDLIB
    return ORIGIN_THIRD_PARTY


def classify_imports(censuses: Sequence[ModuleCensus]) -> tuple[ModuleCensus, ...]:
    """Resolve every import's ``origin``, returning new census records.

    The discovered module set is taken from *censuses* themselves —
    every role, tests included, because an import of a test helper is
    still first-party even though the graph will not carry it.

    Input order is preserved, so a caller can zip the result against
    what it passed in. Idempotent: classifying an already-classified
    tuple returns records equal to the ones it was given.
    """
    modules = frozenset(census.source.module for census in censuses)
    classified: list[ModuleCensus] = []
    for census in censuses:
        imports = tuple(
            replace(record, origin=_origin_of(record, modules)) for record in census.imports
        )
        if imports == census.imports:
            classified.append(census)
        else:
            classified.append(replace(census, imports=imports))
    return tuple(classified)


# ---------------------------------------------------------------------------
# Cycles: Tarjan, iteratively
# ---------------------------------------------------------------------------


def _tarjan_sccs(
    nodes: tuple[str, ...],
    successors: Mapping[str, tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    """Strongly connected components of a directed graph, without recursion.

    *nodes* must be sorted and *successors* must give a sorted tuple for
    every node, which is what makes the result reproducible. Each
    component comes back with its members sorted; the components
    themselves are in the order Tarjan finished them, which is already
    deterministic given sorted inputs.

    An explicit work stack replaces the textbook recursion: a chain of a
    few thousand modules is ordinary in a real repository and would
    otherwise raise ``RecursionError`` on the machine of whoever ran the
    scan.
    """
    index_of: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    pending: list[str] = []
    counter = 0
    components: list[tuple[str, ...]] = []

    for root in nodes:
        if root in index_of:
            continue
        index_of[root] = counter
        lowlink[root] = counter
        counter += 1
        pending.append(root)
        on_stack.add(root)
        # Each frame is (node, index of the next successor to visit).
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, position = work[-1]
            children = successors[node]
            if position < len(children):
                work[-1] = (node, position + 1)
                child = children[position]
                if child not in index_of:
                    index_of[child] = counter
                    lowlink[child] = counter
                    counter += 1
                    pending.append(child)
                    on_stack.add(child)
                    work.append((child, 0))
                elif child in on_stack and index_of[child] < lowlink[node]:
                    lowlink[node] = index_of[child]
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                if lowlink[node] < lowlink[parent]:
                    lowlink[parent] = lowlink[node]
            if lowlink[node] == index_of[node]:
                members: list[str] = []
                while True:
                    member = pending.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node:
                        break
                components.append(tuple(sorted(members)))
    return tuple(components)


def _condensation_order(
    components: tuple[tuple[str, ...], ...],
    successors: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """Leaf-first order over the components: dependencies before dependents.

    Kahn's algorithm on the condensation, which is acyclic by
    construction, with each component keyed by its alphabetically first
    member so independent components come out in a fixed order. A
    component's members are emitted together and in alphabetical order —
    a cycle has no honest internal order, and keeping its members
    adjacent is what tells a reader "these convert as one piece".
    """
    component_of: dict[str, int] = {}
    for index, members in enumerate(components):
        for member in members:
            component_of[member] = index

    depends_on: dict[int, set[int]] = {index: set() for index in range(len(components))}
    consumers: dict[int, set[int]] = {index: set() for index in range(len(components))}
    for index, members in enumerate(components):
        for member in members:
            for target in successors[member]:
                other = component_of[target]
                if other != index:
                    depends_on[index].add(other)
    for index, dependencies in depends_on.items():
        for dependency in dependencies:
            consumers[dependency].add(index)

    outstanding = {index: len(targets) for index, targets in depends_on.items()}
    # (alphabetically first member, component index): the first element is
    # unique across components, so the heap order is total and stable.
    ready: list[tuple[str, int]] = [
        (components[index][0], index) for index, count in outstanding.items() if count == 0
    ]
    heapq.heapify(ready)

    order: list[str] = []
    emitted: set[int] = set()
    while ready:
        _key, index = heapq.heappop(ready)
        order.extend(components[index])
        emitted.add(index)
        for consumer in sorted(consumers[index]):
            outstanding[consumer] -= 1
            if outstanding[consumer] == 0:
                heapq.heappush(ready, (components[consumer][0], consumer))

    if len(emitted) != len(components):
        # Unreachable: the condensation of an SCC decomposition is
        # acyclic, so Kahn always drains it. Kept because every consumer
        # of ``order`` (the report's conversion list, ``adopt status``'s
        # next module) assumes every module is in it; a silent omission
        # would quietly hide a module from the whole retrofit.
        for index in sorted(set(range(len(components))) - emitted, key=lambda i: components[i][0]):
            order.extend(components[index])

    return tuple(order)


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def build_graph(censuses: Sequence[ModuleCensus]) -> GraphFacts:
    """The first-party import graph of a scanned tree, and the order it implies.

    Classifies the imports itself, keeps the application modules (tests
    are left out entirely), splits load-time edges from deferred ones,
    finds the cycles, and returns everything sorted so two scans of an
    unchanged tree produce byte-identical JSON.
    """
    resolved = classify_imports(censuses)
    # Every discovered module resolves an import, tests included — but only
    # the non-test ones become nodes. Two files claiming one dotted name
    # (a vendored copy, say) are one node, not two.
    modules = frozenset(census.source.module for census in resolved)
    node_names = {
        census.source.module for census in resolved if census.source.role != _TEST_ROLE
    }
    nodes = tuple(sorted(node_names))
    in_graph = frozenset(nodes)

    load_pairs: set[tuple[str, str]] = set()
    deferred_pairs: set[tuple[str, str]] = set()
    for census in resolved:
        importer = census.source.module
        if importer not in in_graph:
            continue
        for record in census.imports:
            if record.origin != ORIGIN_FIRST_PARTY:
                continue
            for target in _import_targets(record, modules):
                if target == importer or target not in in_graph:
                    continue
                if record.deferred or record.type_checking:
                    deferred_pairs.add((importer, target))
                else:
                    load_pairs.add((importer, target))

    edges = tuple(sorted(load_pairs))
    deferred_edges = tuple(sorted(deferred_pairs))

    successor_lists: dict[str, list[str]] = {node: [] for node in nodes}
    for importer, target in edges:
        successor_lists[importer].append(target)
    successors: dict[str, tuple[str, ...]] = {
        node: tuple(sorted(targets)) for node, targets in successor_lists.items()
    }

    components = _tarjan_sccs(nodes, successors)
    cycles = tuple(sorted(members for members in components if len(members) > 1))
    order = _condensation_order(components, successors)

    fan_in_counts = dict.fromkeys(nodes, 0)
    fan_out_counts = dict.fromkeys(nodes, 0)
    for importer, target in edges:
        fan_out_counts[importer] += 1
        fan_in_counts[target] += 1

    return GraphFacts(
        edges=edges,
        deferred_edges=deferred_edges,
        cycles=cycles,
        order=order,
        # Every node carries a row, zeroes included, so a reader never has
        # to decide whether a missing name means "nobody imports it" or
        # "the scan forgot it". Sorted by module name, like every other
        # pair tuple in the model.
        fan_in=tuple((node, fan_in_counts[node]) for node in nodes),
        fan_out=tuple((node, fan_out_counts[node]) for node in nodes),
    )
