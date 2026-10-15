"""End-to-end tests: the whole viewer, in one process, against one real project.

Everything upstream of this file tests a seam. This file tests the
journey a person actually takes: ``s0ma studi0`` on a built project, a
browser asking for the page, an editor changing a source, ``s0ma build``
landing, and the page learning about it — with nothing stubbed anywhere
along the way.

Two properties are pinned here that no other test can pin:

* **The page is part of the build.** ``/`` and the two ``/assets``
  routes answer with the bytes the transpiler embedded from
  ``s0ma_src/assets/`` (FR-STUDI0-8), and those bytes are still the
  files on disk. studi0 does not serve a directory it happens to find
  next to itself, and it does not template anything into them: what a
  browser receives is what the model carries. The build manifest is
  asked the same question from the other side — it must record all
  three embedded files, with hashes.

* **A build that adds a component reaches the page.** The full arc:
  fresh, then an edit makes it honestly stale, then a real rebuild makes
  it fresh again with a component that was not there before — visible in
  ``/api/graph`` under a sequence number ``/api/state`` agrees with. The
  frontend's own reaction to that arc (the materialize beat) is a
  browser matter, verified in front of a person; what is provable here
  is that the truth arrives at all.

Every wait is on a condition, never on a clock: builds are slow, Windows
CI is slower, and a suite tuned to a sleep is a suite that fails on
someone else's machine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from conftest import build_project, wait_until

from s0ma_studi0 import sh0w_assets

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import ServedStudi0

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = PACKAGE_ROOT / "s0ma_src" / "assets"
BUILD_MANIFEST = PACKAGE_ROOT / "src" / "s0ma_studi0" / "_built" / "build.s0ma.json"

#: (route, content type, embedded constant, source file) for each of the
#: three files the page is made of.
SERVED_ASSETS = [
    ("/", "text/html; charset=utf-8", sh0w_assets.INDEX_HTML, "index.html"),
    ("/assets/app.css", "text/css; charset=utf-8", sh0w_assets.APP_CSS, "app.css"),
    (
        "/assets/app.js",
        "text/javascript; charset=utf-8",
        sh0w_assets.APP_JS,
        "app.js",
    ),
]

#: A component the golden project does not have. Appended to a module
#: source and built, it is the smallest honest "the model grew" event:
#: one new canonical id, in an existing module, changing nothing else.
PROBE_MODULE = "task_service"
PROBE_ID = "task_service::_studi0_probe_constant"
PROBE_CELL = """
cell _studi0_probe_constant :: APPLICATION
    kind: CONSTANT
    visibility: INTERNAL
    intent: "A component the end-to-end test adds mid-session, so a build has something new to say"
    schema: "int constant = 1"
    invariants: none
    covered_by: none
    ---
    _studi0_probe_constant = 1
"""


def _await_state(studi0: ServedStudi0, **expected: object) -> dict[str, Any]:
    """Wait until ``/api/state`` reports every *expected* field."""

    def reading() -> dict[str, Any] | None:
        document = studi0.json("/api/state")
        for key, value in expected.items():
            if document.get(key) != value:
                return None
        return document

    return wait_until(reading, what=f"/api/state to report {expected!r}")


# ---------------------------------------------------------------------------
# The page is part of the build
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "content_type", "embedded", "filename"),
    SERVED_ASSETS,
    ids=[entry[3] for entry in SERVED_ASSETS],
)
def test_the_page_is_served_from_the_build(
    launch_studi0: Callable[..., ServedStudi0],
    built_project: Path,
    path: str,
    content_type: str,
    embedded: str,
    filename: str,
) -> None:
    """Each route answers with the embedded bytes, exactly (FR-STUDI0-8)."""
    studi0 = launch_studi0(built_project)
    status, served_type, body = studi0.get(path)

    assert status == 200
    assert served_type == content_type
    assert body == embedded.encode("utf-8")
    # A cached page is a page that stops telling the truth after the
    # next release.
    assert studi0.header(path, "Cache-Control") == "no-store"


@pytest.mark.parametrize(
    ("embedded", "filename"),
    [(entry[2], entry[3]) for entry in SERVED_ASSETS],
    ids=[entry[3] for entry in SERVED_ASSETS],
)
def test_the_embedded_bytes_are_the_authored_file(
    embedded: str, filename: str
) -> None:
    """The build's copy still matches the file it was embedded from.

    This is the drift tripwire for the dogfood: edit an asset, forget to
    rebuild, and the page a user sees is the old one. Comparing text
    rather than bytes is deliberate — the embed reads UTF-8, so this
    fails on content drift and not on how a checkout wrote its line
    endings.
    """
    assert embedded == (ASSET_DIR / filename).read_text(encoding="utf-8")


def test_the_manifest_records_every_embedded_file() -> None:
    """studi0's own build manifest names the three files, with hashes.

    The other side of FR-STUDI0-8: the page is not merely served from
    the build, it is *accounted for* by the build, so a change to any of
    the three is a change the build system can see.
    """
    manifest = json.loads(BUILD_MANIFEST.read_text(encoding="utf-8"))
    embedded = manifest["external_content_files"]

    assert set(embedded) == {
        "sh0w_assets::INDEX_HTML",
        "sh0w_assets::APP_CSS",
        "sh0w_assets::APP_JS",
    }
    for key, entry in sorted(embedded.items()):
        assert entry["path"].startswith("assets/"), key
        assert entry["hash"].startswith("sha256:"), key


def test_nothing_the_page_asks_for_leaves_this_machine(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """FR-STUDI0-7 checked on the wire, not in the source tree.

    The file-level tripwire in ``test_frontend_assets.py`` checks what
    was authored; this checks what is actually delivered. A page that
    reaches for a CDN is a page that stops working offline and starts
    telling someone else what its user is looking at.
    """
    studi0 = launch_studi0(built_project)
    for path, _, _, _ in SERVED_ASSETS:
        _, _, body = studi0.get(path)
        text = body.decode("utf-8")
        assert "http://" not in text, path
        assert "https://" not in text, path


# ---------------------------------------------------------------------------
# A build reaches the page
# ---------------------------------------------------------------------------


def test_a_rebuild_that_adds_a_component_reaches_the_page(
    launch_studi0: Callable[..., ServedStudi0], mutable_project: Path
) -> None:
    """Edit, go stale, rebuild, and the new component is being served.

    The arc a person watches with the page open, asserted from the
    outside: nothing is called on the session, nothing is stubbed, and
    every step waits for the watch to notice on its own.
    """
    studi0 = launch_studi0(mutable_project)

    start = _await_state(studi0, build_status="fresh")
    assert start["stale_modules"] == []
    before = studi0.json("/api/graph")["graph"]
    assert PROBE_ID not in before["components"]
    assert PROBE_ID not in before["nodes"]

    # 1. The edit alone. The declarations the build recorded have not
    #    changed, so the graph must not change either — only the honest
    #    statement that it is no longer current.
    source = mutable_project / "src" / f"{PROBE_MODULE}.s0ma"
    source.write_text(
        source.read_text(encoding="utf-8") + PROBE_CELL,
        encoding="utf-8",
        newline="\n",
    )
    stale = _await_state(studi0, build_status="stale")
    assert stale["stale_modules"] == [PROBE_MODULE]
    assert stale["seq"] == start["seq"] + 1
    assert studi0.json("/api/graph")["graph"]["nodes"] == before["nodes"]

    # 2. The build. Now the model really has grown.
    build_project(mutable_project)
    fresh = _await_state(studi0, build_status="fresh")
    assert fresh["stale_modules"] == []
    # A build rewrites a directory of files, and the watch reads that
    # directory while it is being rewritten, so the number of readings
    # it publishes on the way through is not a fixed quantity. That it
    # only ever moves forward is.
    assert fresh["seq"] > stale["seq"]

    graph = studi0.json("/api/graph")
    assert graph["seq"] >= fresh["seq"]
    assert PROBE_ID in graph["graph"]["components"]
    assert PROBE_ID in graph["graph"]["nodes"]

    probe = graph["graph"]["components"][PROBE_ID]
    assert probe["module"] == PROBE_MODULE
    assert probe["declaration_type"] == "cell"
    assert probe["intent"]["state"] == "value"

    # Everything that was there before is still there: a build that adds
    # is not a build that replaces.
    for canonical_id in before["nodes"]:
        assert canonical_id in graph["graph"]["nodes"]


def test_the_page_and_the_graph_are_served_by_one_process(
    launch_studi0: Callable[..., ServedStudi0], built_project: Path
) -> None:
    """One port serves the document, its assets, and its data.

    A viewer split across two origins would need a second thing to
    launch, a second thing to secure, and a story about CORS. studi0
    has one socket, on loopback, and everything the page needs is
    behind it.
    """
    studi0 = launch_studi0(built_project)
    assert studi0.host == "127.0.0.1"
    for path in ("/", "/assets/app.css", "/assets/app.js", "/api/state"):
        status, _, _ = studi0.get(path)
        assert status == 200, path
    assert studi0.json("/api/graph")["graph"]["schema"] == "s0ma-graph@2"
