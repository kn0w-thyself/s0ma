"""The first-party import graph of a scanned tree (B2).

``s0ma_dsl/adopt/graph.py`` answers the two questions rung 0 exists to
answer: where does each import come from, and in what order can the
modules be converted without the half-converted tree ceasing to import.
These tests lock the answers the rest of the retrofit family builds on:

- **Classification is worked out, not inherited.** The census leaves
  what it cannot decide as ``"unresolved"``; the graph must never let
  that placeholder through as an answer, and must give the same answer
  when run twice.
- **Order is leaf-first, and alphabetical only as a tie-break.** Several
  cases below are named so that the alphabetical order is *wrong*; a
  regression that sorted instead of ordering would fail them.
- **A cycle is reported, never raised.** A scan reads a codebase nobody
  has tidied yet. Knots are findings.
- **A deferred import is not a cycle.** Function-scoped and
  ``TYPE_CHECKING`` imports are exactly how a working project hides one,
  and calling them cycles would send a reader chasing nothing.
- **Tests are not in the graph.** A test suite imports everything; left
  in, it would make every module look depended-upon.
- **Size is not a surprise.** Two thousand modules in a chain is an
  ordinary monorepo, and must neither hit the recursion limit nor take
  noticeable time.

Every census here is built by hand from the frozen model, so these tests
do not depend on the census reader or on the brownfield fixtures.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from s0ma_dsl.adopt.graph import (
    ORIGIN_FIRST_PARTY,
    ORIGIN_STDLIB,
    ORIGIN_THIRD_PARTY,
    ORIGIN_UNRESOLVED,
    build_graph,
    classify_imports,
)
from s0ma_dsl.adopt.model import ImportFact, ModuleCensus, SourceFile, dump_json

if TYPE_CHECKING:
    from collections.abc import Sequence

# ---------------------------------------------------------------------------
# Hand-built censuses
#
# Only the fields the graph reads carry meaning here: the source's
# module name and role, and the import records. Everything else is a
# valid placeholder, because no field in the model has a default and a
# census must be constructed whole.
# ---------------------------------------------------------------------------

EMPTY_HASH = "sha256:" + "0" * 64


def an_import(
    module: str,
    *,
    names: Sequence[str] = (),
    line: int = 1,
    deferred: bool = False,
    type_checking: bool = False,
    origin: str = ORIGIN_UNRESOLVED,
) -> ImportFact:
    """One import record, defaulting to what the census reader leaves behind."""
    return ImportFact(
        module=module,
        names=tuple(names),
        line=line,
        deferred=deferred,
        type_checking=type_checking,
        origin=origin,
    )


def a_module(
    module: str,
    *imports: ImportFact,
    role: str = "app",
    path: str | None = None,
) -> ModuleCensus:
    """One census for *module*, carrying only the imports the graph reads."""
    return ModuleCensus(
        source=SourceFile(
            path=path if path is not None else "src/" + module.replace(".", "/") + ".py",
            module=module,
            source_root="src",
            role=role,
        ),
        lines=10,
        sloc=8,
        entities=(),
        imports=tuple(imports),
        dunder_all=None,
        has_main_guard=False,
        top_level_effects=0,
        parse_error=None,
        content_hash=EMPTY_HASH,
    )


def origins(censuses: Sequence[ModuleCensus]) -> dict[tuple[str, str], str]:
    """``(module, import target) -> origin``, for compact assertions."""
    return {
        (census.source.module, record.module): record.origin
        for census in censuses
        for record in census.imports
    }


# ---------------------------------------------------------------------------
# T1 — classifying an import's origin
# ---------------------------------------------------------------------------


def test_first_party_resolves_by_longest_prefix() -> None:
    censuses = [
        a_module("pkg"),
        a_module("pkg.deep"),
        a_module(
            "caller",
            an_import("pkg.deep.leaf"),  # import pkg.deep.leaf  -> pkg.deep
            an_import("pkg.missing"),  # import pkg.missing    -> pkg
        ),
    ]

    graph = build_graph(censuses)

    assert ("caller", "pkg.deep") in graph.edges
    assert ("caller", "pkg") in graph.edges


def test_from_import_reaches_a_submodule_when_the_name_is_one() -> None:
    censuses = [
        a_module("shop"),
        a_module("shop.cart"),
        # from shop import cart, checkout — ``cart`` is a module, ``checkout``
        # is a function defined in shop/__init__.py.
        a_module("web", an_import("shop", names=("cart", "checkout"))),
    ]

    graph = build_graph(censuses)

    assert ("web", "shop.cart") in graph.edges
    assert ("web", "shop") in graph.edges


def test_plain_package_import_does_not_reach_into_the_package() -> None:
    """``import shop`` depends on the package, not on every module in it."""
    censuses = [
        a_module("shop"),
        a_module("shop.cart"),
        a_module("web", an_import("shop")),
    ]

    graph = build_graph(censuses)

    assert graph.edges == (("web", "shop"),)


def test_stdlib_and_third_party_are_told_apart() -> None:
    censuses = classify_imports(
        [
            a_module(
                "app",
                an_import("os"),
                an_import("os.path"),
                an_import("typing", names=("TYPE_CHECKING",)),
                an_import("requests"),
                an_import("requests.adapters", names=("HTTPAdapter",)),
            )
        ]
    )

    assert origins(censuses) == {
        ("app", "os"): ORIGIN_STDLIB,
        ("app", "os.path"): ORIGIN_STDLIB,
        ("app", "typing"): ORIGIN_STDLIB,
        ("app", "requests"): ORIGIN_THIRD_PARTY,
        ("app", "requests.adapters"): ORIGIN_THIRD_PARTY,
    }


def test_a_first_party_module_shadows_a_stdlib_name() -> None:
    """A flat project with its own ``types.py`` really does shadow stdlib."""
    censuses = classify_imports(
        [
            a_module("types", path="types.py"),
            a_module("app", an_import("types", names=("Shape",))),
        ]
    )

    assert origins(censuses)[("app", "types")] == ORIGIN_FIRST_PARTY


def test_a_relative_import_above_the_top_package_stays_unresolved() -> None:
    censuses = classify_imports(
        [
            a_module("pkg.core"),
            a_module(
                "pkg.edge",
                an_import("..outside", names=("thing",)),
                an_import("", names=("other",)),
                an_import("pkg.core", names=("run",)),
            ),
        ]
    )

    resolved = origins(censuses)
    assert resolved[("pkg.edge", "..outside")] == ORIGIN_UNRESOLVED
    assert resolved[("pkg.edge", "")] == ORIGIN_UNRESOLVED
    assert resolved[("pkg.edge", "pkg.core")] == ORIGIN_FIRST_PARTY

    # An unresolved target contributes nothing to the graph.
    assert build_graph(censuses).edges == (("pkg.edge", "pkg.core"),)


def test_classification_ignores_whatever_origin_it_was_handed() -> None:
    """A wrong incoming ``origin`` is corrected, not trusted."""
    censuses = classify_imports(
        [
            a_module("lib"),
            a_module("app", an_import("lib", origin=ORIGIN_THIRD_PARTY)),
        ]
    )

    assert origins(censuses)[("app", "lib")] == ORIGIN_FIRST_PARTY


def test_classification_is_idempotent_and_preserves_input_order() -> None:
    censuses = [
        a_module("zeta", an_import("os"), an_import("alpha")),
        a_module("alpha", an_import("requests")),
    ]

    once = classify_imports(censuses)
    twice = classify_imports(once)

    assert [census.source.module for census in once] == ["zeta", "alpha"]
    assert twice == once
    # The second pass changes nothing, so the records are passed straight
    # through rather than copied.
    assert all(a is b for a, b in zip(once, twice, strict=True))


def test_classified_censuses_are_new_records_and_leave_the_input_alone() -> None:
    original = a_module("app", an_import("os"))
    classified = classify_imports([original])

    assert classified[0] is not original
    assert original.imports[0].origin == ORIGIN_UNRESOLVED
    assert classified[0].imports[0].origin == ORIGIN_STDLIB
    # Everything but the imports is carried over untouched.
    assert classified[0].source == original.source
    assert classified[0].content_hash == original.content_hash


def test_test_file_imports_are_still_classified() -> None:
    censuses = classify_imports(
        [
            a_module("app"),
            a_module(
                "tests.test_app",
                an_import("app", names=("run",)),
                an_import("pytest"),
                role="test",
                path="tests/test_app.py",
            ),
        ]
    )

    resolved = origins(censuses)
    assert resolved[("tests.test_app", "app")] == ORIGIN_FIRST_PARTY
    assert resolved[("tests.test_app", "pytest")] == ORIGIN_THIRD_PARTY


# ---------------------------------------------------------------------------
# T2 — edges: what runs at load time, and what is in the graph at all
# ---------------------------------------------------------------------------


def test_deferred_and_type_checking_imports_are_not_load_time_edges() -> None:
    censuses = [
        a_module("lib"),
        a_module("helpers"),
        a_module(
            "app",
            an_import("lib", names=("run",), deferred=True),
            an_import("helpers", names=("Kind",), type_checking=True),
        ),
    ]

    graph = build_graph(censuses)

    assert graph.edges == ()
    assert graph.deferred_edges == (("app", "helpers"), ("app", "lib"))


def test_an_import_at_both_levels_appears_in_both_tuples() -> None:
    censuses = [
        a_module("lib"),
        a_module(
            "app",
            an_import("lib", names=("run",), line=1),
            an_import("lib", names=("late",), line=20, deferred=True),
        ),
    ]

    graph = build_graph(censuses)

    assert graph.edges == (("app", "lib"),)
    assert graph.deferred_edges == (("app", "lib"),)


def test_self_imports_are_dropped() -> None:
    graph = build_graph([a_module("app", an_import("app", names=("helper",)))])

    assert graph.edges == ()
    assert graph.cycles == ()
    assert graph.order == ("app",)


def test_test_files_are_not_nodes_and_carry_no_edges() -> None:
    censuses = [
        a_module("app", an_import("lib", names=("run",))),
        a_module("lib"),
        a_module(
            "tests.test_app",
            an_import("app", names=("main",)),
            role="test",
            path="tests/test_app.py",
        ),
        a_module("tests", role="test", path="tests/__init__.py"),
    ]

    graph = build_graph(censuses)

    assert graph.order == ("lib", "app")
    assert graph.edges == (("app", "lib"),)
    assert [name for name, _count in graph.fan_in] == ["app", "lib"]
    assert all("test" not in name for name in graph.order)


def test_scripts_and_package_markers_stay_in_the_graph() -> None:
    """Only the test role is excluded; everything else is convertible code."""
    censuses = [
        a_module("pkg", role="package_marker", path="src/pkg/__init__.py"),
        a_module("pkg.core"),
        a_module("run", an_import("pkg.core", names=("go",)), role="script", path="run.py"),
    ]

    graph = build_graph(censuses)

    assert set(graph.order) == {"pkg", "pkg.core", "run"}
    assert graph.edges == (("run", "pkg.core"),)


def test_a_module_that_could_not_be_parsed_is_still_in_the_order() -> None:
    """A file the census could not read is still a file somebody must convert."""
    broken = ModuleCensus(
        source=SourceFile(
            path="src/broken.py", module="broken", source_root="src", role="app"
        ),
        lines=4,
        sloc=4,
        entities=(),
        imports=(),
        dunder_all=None,
        has_main_guard=False,
        top_level_effects=0,
        parse_error="line 3: unexpected indent",
        content_hash=EMPTY_HASH,
    )

    graph = build_graph([broken, a_module("app", an_import("os"))])

    assert graph.order == ("app", "broken")
    assert dict(graph.fan_in)["broken"] == 0


def test_imports_of_things_outside_the_project_are_not_edges() -> None:
    censuses = [
        a_module("app", an_import("os"), an_import("requests"), an_import("lib")),
        a_module("lib"),
    ]

    assert build_graph(censuses).edges == (("app", "lib"),)


def test_two_files_claiming_one_module_name_make_one_node() -> None:
    censuses = [
        a_module("lib", path="src/lib.py"),
        a_module("lib", an_import("os"), path="vendored/lib.py"),
        a_module("app", an_import("lib", names=("run",))),
    ]

    graph = build_graph(censuses)

    assert graph.order == ("lib", "app")
    assert len(graph.fan_in) == 2


# ---------------------------------------------------------------------------
# T3 — cycles and the conversion order
# ---------------------------------------------------------------------------


def test_chain_orders_leaf_first() -> None:
    censuses = [
        a_module("a", an_import("b", names=("B",))),
        a_module("b", an_import("c", names=("C",))),
        a_module("c"),
    ]

    graph = build_graph(censuses)

    assert graph.order == ("c", "b", "a")
    assert graph.cycles == ()
    assert graph.edges == (("a", "b"), ("b", "c"))


def test_diamond_orders_the_base_first_and_breaks_ties_alphabetically() -> None:
    censuses = [
        a_module("top", an_import("right", names=("R",)), an_import("left", names=("L",))),
        a_module("left", an_import("base", names=("B",))),
        a_module("right", an_import("base", names=("B",))),
        a_module("base"),
    ]

    graph = build_graph(censuses)

    assert graph.order == ("base", "left", "right", "top")


def test_two_module_cycle_is_reported_and_kept_adjacent() -> None:
    censuses = [
        a_module("catalog", an_import("lending", names=("Loan",))),
        a_module("lending", an_import("catalog", names=("Book",))),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == (("catalog", "lending"),)
    assert graph.order == ("catalog", "lending")


def test_three_module_cycle_with_a_tail_orders_around_the_knot() -> None:
    """Names chosen so that alphabetical order would be wrong on every count."""
    censuses = [
        # The knot: mid_a -> mid_b -> mid_c -> mid_a, and it needs zbase.
        a_module("mid_a", an_import("mid_b", names=("B",)), an_import("zbase", names=("Z",))),
        a_module("mid_b", an_import("mid_c", names=("C",))),
        a_module("mid_c", an_import("mid_a", names=("A",))),
        # The tail hangs off the knot.
        a_module("atail", an_import("mid_a", names=("A",))),
        a_module("zbase"),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == (("mid_a", "mid_b", "mid_c"),)
    assert graph.order == ("zbase", "mid_a", "mid_b", "mid_c", "atail")


def test_a_deferred_import_is_not_a_cycle() -> None:
    """The escape hatch a working project already uses must read as one."""
    censuses = [
        a_module("catalog", an_import("lending", names=("Loan",))),
        # lending imports catalog inside a function, which is why the real
        # project still imports cleanly.
        a_module("lending", an_import("catalog", names=("Book",), line=40, deferred=True)),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == ()
    assert graph.edges == (("catalog", "lending"),)
    assert graph.deferred_edges == (("lending", "catalog"),)
    assert graph.order == ("lending", "catalog")


def test_a_type_checking_import_is_not_a_cycle_either() -> None:
    censuses = [
        a_module("models", an_import("store", names=("Store",))),
        a_module("store", an_import("models", names=("Book",), type_checking=True)),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == ()
    assert graph.order == ("store", "models")


def test_two_separate_cycles_are_both_reported_in_sorted_order() -> None:
    censuses = [
        a_module("x1", an_import("x2", names=("N",))),
        a_module("x2", an_import("x1", names=("N",))),
        a_module("b1", an_import("b2", names=("N",))),
        a_module("b2", an_import("b1", names=("N",))),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == (("b1", "b2"), ("x1", "x2"))
    assert graph.order == ("b1", "b2", "x1", "x2")


def test_isolated_modules_all_appear_in_the_order() -> None:
    censuses = [a_module("solo_b"), a_module("solo_a"), a_module("solo_c")]

    graph = build_graph(censuses)

    assert graph.order == ("solo_a", "solo_b", "solo_c")


def test_relative_imports_across_sub_packages_resolve_and_order() -> None:
    """Relative forms arrive already absolute; the graph just has to place them."""
    censuses = [
        a_module("pkg", path="src/pkg/__init__.py"),
        a_module("pkg.util"),
        a_module("pkg.core", path="src/pkg/core/__init__.py"),
        a_module("pkg.core.sibling"),
        a_module(
            "pkg.core.engine",
            # from . import sibling
            an_import("pkg.core", names=("sibling",)),
            # from ..util import helper
            an_import("pkg.util", names=("helper",)),
        ),
    ]

    graph = build_graph(censuses)

    assert ("pkg.core.engine", "pkg.core.sibling") in graph.edges
    assert ("pkg.core.engine", "pkg.util") in graph.edges
    assert graph.order.index("pkg.core.sibling") < graph.order.index("pkg.core.engine")
    assert graph.order.index("pkg.util") < graph.order.index("pkg.core.engine")


def test_a_re_exporting_package_init_is_not_a_cycle() -> None:
    """The implicit parent-package import is deliberately not an edge.

    Python does run ``pkg/__init__.py`` before ``pkg/models.py``, so
    modelling that would make every ordinary re-exporting package a
    single cycle spanning all of its modules — a conversion order nobody
    can act on. Only written imports count.
    """
    censuses = [
        # pkg/__init__.py: from pkg.models import Book
        a_module("pkg", an_import("pkg.models", names=("Book",)), path="src/pkg/__init__.py"),
        # pkg/models.py: from pkg.errors import PkgError
        a_module("pkg.models", an_import("pkg.errors", names=("PkgError",))),
        a_module("pkg.errors"),
    ]

    graph = build_graph(censuses)

    assert graph.cycles == ()
    assert graph.order == ("pkg.errors", "pkg.models", "pkg")


def test_empty_input_is_an_empty_graph() -> None:
    graph = build_graph([])

    assert graph.edges == ()
    assert graph.deferred_edges == ()
    assert graph.cycles == ()
    assert graph.order == ()
    assert graph.fan_in == ()
    assert graph.fan_out == ()


# ---------------------------------------------------------------------------
# T4 — fan-in and fan-out
# ---------------------------------------------------------------------------


def test_fan_counts_cover_every_node_including_the_zeroes() -> None:
    censuses = [
        a_module("hub"),
        a_module("one", an_import("hub", names=("H",))),
        a_module("two", an_import("hub", names=("H",))),
        a_module("three", an_import("hub", names=("H",)), an_import("one", names=("O",))),
        a_module("lonely"),
    ]

    graph = build_graph(censuses)

    assert dict(graph.fan_in) == {"hub": 3, "lonely": 0, "one": 1, "three": 0, "two": 0}
    assert dict(graph.fan_out) == {"hub": 0, "lonely": 0, "one": 1, "three": 2, "two": 1}
    # Sorted by module name, like every other pair tuple in the model.
    assert [name for name, _count in graph.fan_in] == sorted(name for name, _ in graph.fan_in)
    assert [name for name, _count in graph.fan_out] == sorted(name for name, _ in graph.fan_out)


def test_fan_counts_ignore_deferred_edges() -> None:
    censuses = [
        a_module("lib"),
        a_module("app", an_import("lib", names=("run",), deferred=True)),
    ]

    graph = build_graph(censuses)

    assert dict(graph.fan_in) == {"app": 0, "lib": 0}
    assert dict(graph.fan_out) == {"app": 0, "lib": 0}


# ---------------------------------------------------------------------------
# Determinism — the whole family's committed artifacts depend on it
# ---------------------------------------------------------------------------


def _tangled_censuses() -> list[ModuleCensus]:
    return [
        a_module("app.cli", an_import("app.api", names=("handle",)), an_import("os")),
        a_module("app.api", an_import("app.domain", names=("Book",)), an_import("requests")),
        a_module("app.domain", an_import("app.store", names=("Store",), type_checking=True)),
        a_module("app.store", an_import("app.domain", names=("Book",), deferred=True)),
        a_module("app", path="src/app/__init__.py"),
        a_module("tests.test_api", an_import("app.api"), role="test", path="tests/test_api.py"),
    ]


def test_the_same_tree_gives_byte_identical_json_twice() -> None:
    first = build_graph(_tangled_censuses())
    second = build_graph(_tangled_censuses())

    assert dump_json(first.to_dict()) == dump_json(second.to_dict())


def test_the_answer_does_not_depend_on_the_order_the_files_arrived_in() -> None:
    forward = build_graph(_tangled_censuses())
    backward = build_graph(list(reversed(_tangled_censuses())))

    assert forward == backward


def test_every_sequence_in_the_graph_comes_out_sorted() -> None:
    graph = build_graph(_tangled_censuses())

    assert list(graph.edges) == sorted(graph.edges)
    assert list(graph.deferred_edges) == sorted(graph.deferred_edges)
    assert list(graph.cycles) == sorted(graph.cycles)
    for cycle in graph.cycles:
        assert list(cycle) == sorted(cycle)


def test_the_order_holds_every_node_exactly_once_and_respects_every_edge() -> None:
    graph = build_graph(_tangled_censuses())

    assert len(graph.order) == len(set(graph.order))
    assert set(graph.order) == {name for name, _count in graph.fan_in}
    position = {module: index for index, module in enumerate(graph.order)}
    for importer, target in graph.edges:
        assert position[target] < position[importer]


# ---------------------------------------------------------------------------
# Size — a real monorepo must not surprise anyone
# ---------------------------------------------------------------------------


def test_two_thousand_module_chain_finishes_quickly_and_without_recursion() -> None:
    names = [f"m{index:04d}" for index in range(2000)]
    censuses = [
        a_module(name, an_import(names[index + 1], names=("nxt",)))
        if index + 1 < len(names)
        else a_module(name)
        for index, name in enumerate(names)
    ]

    started = time.perf_counter()
    graph = build_graph(censuses)
    elapsed = time.perf_counter() - started

    assert graph.cycles == ()
    assert len(graph.order) == 2000
    assert graph.order[0] == "m1999"
    assert graph.order[-1] == "m0000"
    assert elapsed < 2.0, f"2,000-module chain took {elapsed:.3f}s"


def test_two_thousand_module_cycle_is_one_component_and_still_quick() -> None:
    names = [f"c{index:04d}" for index in range(2000)]
    censuses = [
        a_module(name, an_import(names[(index + 1) % len(names)], names=("nxt",)))
        for index, name in enumerate(names)
    ]

    started = time.perf_counter()
    graph = build_graph(censuses)
    elapsed = time.perf_counter() - started

    assert len(graph.cycles) == 1
    assert graph.cycles[0] == tuple(names)
    assert graph.order == tuple(names)
    assert elapsed < 2.0, f"2,000-module cycle took {elapsed:.3f}s"
