"""Contract tests for the studi0 graph API (plan §3.5).

Every test here speaks HTTP to a real studi0 serving a real, built
s0ma project — the dsl's ``golden_project`` fixture, staged and built
into a temporary directory. Nothing is stubbed: if the payload is
wrong, or the watch never notices a change, these fail.

What is pinned:

* **The two documents' exact key sets**, because a viewer built against
  them is a contract, not a convention. The key sets and the schema
  strings themselves live in the package now — ``studi0_state``
  declares them — so what is pinned here is that the served documents
  match what studi0 says it serves, plus a freeze on the declared
  values so promoting them did not lose the pin.
* **That the declared route table is the served routing table.**
  ``studi0_server.ROUTE_TABLE`` says what studi0 serves; the routing
  decision is still taken in ``route_request``. A route named in one
  and absent from the other fails here, which is what keeps a table
  meant for readers from becoming a table that is merely plausible.
* **That ``/api/graph`` is `s0ma_dsl.graph_export`'s own output** and
  nothing else — there is one graph mechanism in the system, and this
  is the assertion that keeps studi0 from quietly growing a second.
* **That state wrappers survive the trip.** ``{"state": "pending"}`` is
  authoring debt a renderer must be able to see; a server that
  flattened it would be deciding, behind the reader's back, that the
  debt is not worth showing.
* **That the truth follows the tree**: editing a source makes the build
  stale, rebuilding makes it fresh again, removing the manifest makes
  freshness unknowable — and ``seq`` advances on each of those, once.
"""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
from typing import TYPE_CHECKING, Any

from conftest import BUILD_DIR_NAME, PROBE_MODULE, build_project, touch_source, wait_until
from s0ma_dsl.graph_export import collect_graph
from s0ma_studi0.studi0_server import ROUTE_TABLE, route_request
from s0ma_studi0.studi0_state import (
    CARRIED_GRAPH_SCHEMA,
    GRAPH_DOCUMENT_KEYS,
    GRAPH_SCHEMA,
    NARRATION_BLOCK_KEYS,
    STATE_DOCUMENT_KEYS,
    STATE_SCHEMA,
)

import s0ma_studi0

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import ServedStudi0

#: The frozen document shapes (plan §3.5), asked of the package rather
#: than written out again here. D4a promoted them out of this file: the
#: package owns its own wire identity, and a test that kept a second
#: copy of it would be pinning the copy.
STATE_KEYS = set(STATE_DOCUMENT_KEYS)
GRAPH_KEYS = set(GRAPH_DOCUMENT_KEYS)

#: The narration block's own frozen shape (M11). It is a nested block
#: rather than three loose keys precisely so that self-report can never
#: sit at the same level as build truth.
NARRATION_KEYS = set(NARRATION_BLOCK_KEYS)

#: The keys every route-table entry carries. Written out here, because
#: a shape asserted against itself asserts nothing.
ROUTE_KEYS = {
    "path",
    "method",
    "purpose",
    "effects",
    "answered_by",
    "media_type",
    "errors",
}

#: The side-effect words a route may declare. studi0 answers GET only
#: and writes nothing on any request path, so the two honest values are
#: "none" (embedded bytes leave the process) and "read" (the session's
#: current reading).
ROUTE_EFFECTS = {"none", "read"}


def _state(studi0: ServedStudi0) -> dict[str, Any]:
    return studi0.json("/api/state")


def _await_status(studi0: ServedStudi0, status: str) -> dict[str, Any]:
    """Wait until ``/api/state`` reports *status*, and return that state."""
    return wait_until(
        lambda: (
            _state(studi0) if _state(studi0)["build_status"] == status else None
        ),
        what=f"build_status to become {status!r}",
    )


# ---------------------------------------------------------------------------
# The documents
# ---------------------------------------------------------------------------


def test_state_document_has_exactly_the_frozen_keys(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """GET /api/state answers the shape plan §3.5 froze, and no more."""
    studi0 = launch_studi0(built_project)
    status, content_type, body = studi0.get("/api/state")

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    document = json.loads(body.decode("utf-8"))
    assert set(document) == STATE_KEYS
    assert document["schema"] == STATE_SCHEMA
    assert document["build_status"] == "fresh"
    assert document["stale_modules"] == []
    assert isinstance(document["seq"], int)
    # A project nobody narrated in says so with an empty window and two
    # zeros — a fact, not an absence to fill in.
    assert set(document["narration"]) == NARRATION_KEYS
    assert document["narration"] == {"entries": [], "total": 0, "invalid": 0}


def test_graph_document_has_exactly_the_frozen_keys(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """GET /api/graph answers the shape plan §3.5 froze, and no more."""
    studi0 = launch_studi0(built_project)
    status, content_type, body = studi0.get("/api/graph")

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    document = json.loads(body.decode("utf-8"))
    assert set(document) == GRAPH_KEYS
    assert document["schema"] == GRAPH_SCHEMA
    # The envelope and the graph it carries version independently: the
    # transport is studi0's, the graph contract is the dsl's.
    assert document["graph"]["schema"] == CARRIED_GRAPH_SCHEMA


def test_graph_is_exactly_what_collect_graph_produces(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """The served graph IS the dsl's export — studi0 adds nothing.

    Guardrail §1.4 in one assertion: there is no second extraction path
    in the system, so anything studi0 shows can be reproduced by asking
    the dsl the same question.
    """
    studi0 = launch_studi0(built_project)
    served = studi0.json("/api/graph")["graph"]

    assert served == collect_graph(built_project, detail="full")
    # And the fixture is only a real check if it actually carries data.
    assert served["nodes"]
    assert served["components"]
    assert served["modules"]


def test_state_wrappers_pass_through_untouched(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """Component intents arrive as IR state wrappers, not flattened strings.

    Projecting ``{"state": "pending", "reason": ...}`` down to a string
    is a rendering decision. Making it here would hide authoring debt
    from every renderer at once.
    """
    studi0 = launch_studi0(built_project)
    components = studi0.json("/api/graph")["graph"]["components"]

    intents = [entry["intent"] for entry in components.values()]
    assert intents, "the fixture produced no components"
    for intent in intents:
        assert isinstance(intent, dict), f"intent was flattened: {intent!r}"
        assert intent["state"] in {"value", "none", "pending"}


def test_both_endpoints_agree_on_seq(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """A quiet project reports one sequence number on both routes."""
    studi0 = launch_studi0(built_project)
    assert studi0.json("/api/state")["seq"] == studi0.json("/api/graph")["seq"]


def test_seq_starts_at_one(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """The first reading a client can see is seq 1, whatever it found."""
    studi0 = launch_studi0(built_project)
    assert studi0.json("/api/state")["seq"] == 1


# ---------------------------------------------------------------------------
# What studi0 declares it serves (D4a)
#
# ``ROUTE_TABLE`` and ``route_request`` are one fact written twice, and
# the whole value of the first is that it cannot drift from the second.
# These are the tests that make that true rather than hoped for.
# ---------------------------------------------------------------------------


def _path_literals(node: ast.expr) -> list[str]:
    """Every string constant in ``node``, flattening one level of sequence."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return [value for element in node.elts for value in _path_literals(element)]
    return []


def _served_paths() -> set[str]:
    """Every path ``route_request`` decides on, read from its own source.

    Structural, not textual: the function's real source is parsed and
    every comparison of ``path`` against a string — ``==`` or ``in`` —
    gives up its literals. A route added to the chain shows up here
    without anyone remembering to add it, which is the direction of
    drift a hand-kept list cannot catch.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(route_request)))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "path"):
            continue
        for operator, comparator in zip(node.ops, node.comparators, strict=True):
            if isinstance(operator, ast.Eq | ast.In):
                found.update(_path_literals(comparator))
    return found


def test_the_declared_route_table_is_the_served_routing_table() -> None:
    """Every declared route is served, and every served route is declared."""
    declared = {entry["path"] for entry in ROUTE_TABLE}
    assert declared, "the route table declares nothing to compare against"
    # ``route_request`` answers "" and "/" alike, and no HTTP request
    # line can carry the empty spelling — so the table declares the one
    # a caller can actually ask for, and the two spellings fold here.
    served = {path or "/" for path in _served_paths()}
    assert served == declared


def test_every_route_table_entry_has_the_declared_shape() -> None:
    """The table's schema field is a promise; this is the one that keeps it."""
    for entry in ROUTE_TABLE:
        assert set(entry) == ROUTE_KEYS, entry.get("path")
        assert entry["path"].startswith("/")
        assert entry["method"] == "GET"
        assert entry["effects"] in ROUTE_EFFECTS
        assert entry["purpose"].strip()
        assert entry["media_type"].strip()


def test_every_route_names_declarations_that_exist() -> None:
    """``answered_by`` points at real registered declarations, not prose.

    A binding nothing answers to is worse than none: a documentation
    build would mint a reference to a component that is not there, and
    the reader would find a dead end where an explanation should be.
    """
    for entry in ROUTE_TABLE:
        named = [item for item in entry["answered_by"].split(",") if item]
        assert named, f"{entry['path']} names nothing that answers it"
        for canonical in named:
            module_name, separator, member = canonical.partition("::")
            assert separator, f"{canonical!r} is not a module::name id"
            module = getattr(s0ma_studi0, module_name, None)
            assert module is not None, f"{canonical!r} names no built module"
            assert hasattr(module, member), f"{canonical!r} names nothing in {module_name}"


def test_every_declared_route_answers_as_declared(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """Each declared path really is served, with the media type declared."""
    studi0 = launch_studi0(built_project)
    for entry in ROUTE_TABLE:
        status, content_type, body = studi0.get(entry["path"])
        assert status == 200, entry["path"]
        assert content_type == entry["media_type"], entry["path"]
        assert body, f"{entry['path']} answered with nothing"


def test_a_path_the_table_does_not_name_is_not_served(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """The fallback is not an entry because it is what happens off the table."""
    declared = {entry["path"] for entry in ROUTE_TABLE}
    studi0 = launch_studi0(built_project)
    for path in ("/api/nope", "/assets/app.map", "/nope"):
        assert path not in declared
        status, _, body = studi0.get(path)
        assert status == 404
        assert json.loads(body.decode("utf-8"))["error"]["code"] == "NOT_FOUND"


def test_the_declared_wire_identities_are_the_frozen_ones() -> None:
    """Promoting the contract out of this file did not lose the pin.

    The tests above compare the served documents against what the
    package declares; this one says what the package is allowed to
    declare. Without it, a rename of a wire key would move both sides
    together and nothing would notice.
    """
    assert STATE_SCHEMA == "s0ma-studi0-state@2"
    assert GRAPH_SCHEMA == "s0ma-studi0-graph@1"
    assert CARRIED_GRAPH_SCHEMA == "s0ma-graph@2"
    assert STATE_DOCUMENT_KEYS == (
        "build_status",
        "narration",
        "schema",
        "seq",
        "stale_modules",
    )
    assert NARRATION_BLOCK_KEYS == ("entries", "invalid", "total")
    assert GRAPH_DOCUMENT_KEYS == ("graph", "schema", "seq")


# ---------------------------------------------------------------------------
# The truth follows the tree
# ---------------------------------------------------------------------------


def test_the_stale_then_fresh_arc(
    launch_studi0: Callable[..., ServedStudi0], mutable_project: Path
) -> None:
    """Edit a source, and studi0 marks the build stale; rebuild, and it clears.

    The whole live loop in one test, because the interesting property is
    the *sequence*: each real change advances ``seq`` by exactly one,
    and the graph itself is unchanged throughout — the edit moved a
    source hash, not a declaration.
    """
    studi0 = launch_studi0(mutable_project)

    fresh = studi0.json("/api/state")
    assert fresh["build_status"] == "fresh"
    assert fresh["seq"] == 1
    nodes_before = studi0.json("/api/graph")["graph"]["nodes"]

    touch_source(mutable_project)
    stale = _await_status(studi0, "stale")
    assert stale["stale_modules"] == [PROBE_MODULE]
    assert stale["seq"] == fresh["seq"] + 1

    build_project(mutable_project)
    refreshed = _await_status(studi0, "fresh")
    assert refreshed["stale_modules"] == []
    assert refreshed["seq"] == stale["seq"] + 1

    graph = studi0.json("/api/graph")
    assert graph["graph"]["nodes"] == nodes_before
    assert graph["seq"] == refreshed["seq"]


def test_deleting_the_manifest_makes_freshness_unknowable(
    launch_studi0: Callable[..., ServedStudi0], mutable_project: Path
) -> None:
    """No manifest means no evidence, so studi0 claims none — but still draws.

    The IR artifacts are still there and still true, so the graph keeps
    being served. What is gone is the ability to say whether it matches
    the sources, and ``missing`` says exactly that.
    """
    studi0 = launch_studi0(mutable_project)
    nodes_before = studi0.json("/api/graph")["graph"]["nodes"]
    before = studi0.json("/api/state")["seq"]

    (mutable_project / BUILD_DIR_NAME / "build.s0ma.json").unlink()

    missing = _await_status(studi0, "missing")
    assert missing["stale_modules"] == []
    assert missing["seq"] == before + 1
    assert studi0.json("/api/graph")["graph"]["nodes"] == nodes_before


def test_a_quiet_project_never_advances_seq(
    launch_studi0: Callable[..., ServedStudi0], mutable_project: Path
) -> None:
    """Many polls over an unchanged project produce exactly one reading.

    ``seq`` is evidence of change, not of elapsed time — a client that
    repainted on every tick would be repainting on nothing.
    """
    studi0 = launch_studi0(mutable_project)
    first = studi0.json("/api/state")["seq"]

    # Let several watch ticks go by, then ask again. The wait is bounded
    # by a real event: the arrival of a stale flip we then undo.
    touch_source(mutable_project)
    _await_status(studi0, "stale")
    build_project(mutable_project)
    _await_status(studi0, "fresh")

    settled = studi0.json("/api/state")["seq"]
    # Exactly two changes happened, so exactly two advances did.
    assert settled == first + 2


# ---------------------------------------------------------------------------
# How the API answers
# ---------------------------------------------------------------------------


def test_api_answers_are_never_cached(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """A cached answer is a stale answer wearing a fresh answer's clothes."""
    studi0 = launch_studi0(built_project)
    for path in ("/", "/api/state", "/api/graph"):
        assert studi0.header(path, "Cache-Control") == "no-store"


def test_api_bodies_are_sorted_key_utf8_json(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """Identical documents are identical bytes on every machine (INV-5)."""
    studi0 = launch_studi0(built_project)
    for path in ("/api/state", "/api/graph"):
        _, _, body = studi0.get(path)
        document = json.loads(body.decode("utf-8"))
        assert body == json.dumps(document, sort_keys=True).encode("utf-8")


def test_no_answer_is_ever_a_traceback(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """Whatever is asked for, the answer is a document."""
    studi0 = launch_studi0(built_project)
    for path in ("/", "/api/state", "/api/graph", "/api/nope", "/nope"):
        _, _, body = studi0.get(path)
        text = body.decode("utf-8")
        assert "Traceback" not in text
        assert "File \"" not in text


def test_payloads_carry_no_absolute_paths(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """INV-5 end to end: nothing served names this machine.

    The payload is checked as raw bytes rather than field by field, so a
    path smuggled into a field this test does not know about still
    fails it.
    """
    studi0 = launch_studi0(built_project)
    _, _, body = studi0.get("/api/graph")
    assert str(built_project).encode("utf-8") not in body
    assert str(built_project.resolve()).encode("utf-8") not in body
