"""Contract tests for ``s0ma_studi0.launch`` and the studi0 host.

Everything here runs against a REAL server: ``launch()`` is started on a
background thread, the tests speak HTTP to it over loopback, and the
fixture shuts it down and asserts the exit code. The properties pinned
are the ones a viewer must never get wrong:

* it binds ``127.0.0.1`` and nothing else — studi0 is never offered to
  another machine;
* port 0 really means "ask the OS", and the printed URL carries the
  port that was actually bound;
* exactly one line is printed, in the frozen form the CLI asserts;
* the browser opens only when the caller asked for it;
* every route answers — the page at ``/``, the graph API from the
  session's current reading, a structured ``NOT_FOUND`` everywhere else
  — and no answer is ever a traceback.

What the graph API *says* is ``tests/test_api.py``'s subject; this
module only pins that the routes exist and that launching one is
honest. The shared harness lives in ``conftest.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from s0ma_studi0 import sh0w_assets, studi0_server, studi0_state

if TYPE_CHECKING:
    from collections.abc import Callable

    from conftest import BrowserSpy, ServedStudi0

#: The frozen console contract (plan §3.4): one line, loopback only.
SERVING_LINE = re.compile(
    r"^studi0 serving (?P<project>.+) at http://127\.0\.0\.1:(?P<port>\d+)/$"
)


def test_binds_loopback_only(launch_studi0: Callable[..., ServedStudi0]) -> None:
    """The socket's own bound address is the loopback address."""
    session = launch_studi0()
    assert session.host == "127.0.0.1"
    assert studi0_server.Studi0ServerConfig.host == "127.0.0.1"
    # And it answers there, so the binding is real rather than declared.
    status, _, _ = session.get("/")
    assert status == 200


def test_ephemeral_port_is_a_real_bound_port(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """port=0 asks the OS for a port; the reported one is the real one."""
    session = launch_studi0(port=0)
    assert session.port > 0
    assert session.port == session.server.socket.getsockname()[1]


def test_serving_line_is_printed_exactly_once(
    launch_studi0: Callable[..., ServedStudi0],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One line, naming the project and the URL actually served."""
    session = launch_studi0()
    assert session.stop() == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1, f"expected one serving line, got {lines!r}"
    match = SERVING_LINE.match(lines[0])
    assert match is not None, f"serving line off contract: {lines[0]!r}"
    assert match.group("project") == session.project_root.name
    assert int(match.group("port")) == session.port
    assert lines[0] == (
        f"studi0 serving {session.project_root.name} "
        f"at http://127.0.0.1:{session.port}/"
    )


def test_browser_opens_at_the_served_url_when_asked(
    launch_studi0: Callable[..., ServedStudi0],
    browser: BrowserSpy,
) -> None:
    """open_browser=True opens exactly the URL that was printed."""
    session = launch_studi0(open_browser=True)
    assert browser.wait(), "webbrowser.open was never called"
    assert browser.urls == [session.url]
    assert session.url == f"http://127.0.0.1:{session.port}/"


def test_browser_stays_closed_when_not_asked(
    launch_studi0: Callable[..., ServedStudi0],
    browser: BrowserSpy,
) -> None:
    """open_browser=False (the --no-open behavior) opens nothing.

    Asserted after the launch thread has finished, so this is "never
    opened", not "not opened yet".
    """
    session = launch_studi0(open_browser=False)
    assert session.stop() == 0
    assert browser.urls == []


def test_root_serves_the_embedded_sh0w_page(
    launch_studi0: Callable[..., ServedStudi0],
    tmp_path: Path,
) -> None:
    """GET / is the sh0w page, carried in the build and served whole."""
    session = launch_studi0(tmp_path / "billing-app")
    status, content_type, body = session.get("/")

    assert status == 200
    assert content_type == "text/html; charset=utf-8"
    assert body == sh0w_assets.INDEX_HTML.encode("utf-8")
    page = body.decode("utf-8")
    assert page.startswith("<!doctype html>")
    # The page pulls the rest of itself from studi0's own routes.
    assert "/assets/app.css" in page
    assert "/assets/app.js" in page


def test_api_state_answers_for_a_project_with_nothing_built(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """A project with no artifacts is reported, not refused.

    ``missing`` is a real value of the frozen contract, and it is the
    true one here: there is no build to judge. Answering 200 with
    ``missing`` says that; answering an error would leave a client
    unable to tell "nothing built" from "studi0 is broken".
    """
    session = launch_studi0()
    status, content_type, body = session.get("/api/state")

    assert status == 200
    assert content_type == "application/json; charset=utf-8"
    document = json.loads(body.decode("utf-8"))
    assert document["build_status"] == "missing"
    assert document["stale_modules"] == []
    assert "Traceback" not in body.decode("utf-8")


def test_api_graph_refuses_to_imply_an_empty_project(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """With nothing built there is no graph, and studi0 says so.

    An empty graph and an unbuilt project render identically, so the
    one answer studi0 must not give here is ``{"nodes": []}``.
    """
    session = launch_studi0()
    status, content_type, body = session.get("/api/graph")

    assert status == 500
    assert content_type == "application/json; charset=utf-8"
    document = json.loads(body.decode("utf-8"))
    assert document == studi0_server.NOT_BUILT_ERROR
    assert document["error"]["code"] == "NOT_BUILT"
    assert document["error"]["message"]
    assert "Traceback" not in body.decode("utf-8")


@pytest.mark.parametrize(
    "path",
    ["/assets/", "/assets/app.map", "/assets/app.js/", "/nope", "/api/anything"],
)
def test_unserved_paths_answer_not_found(
    launch_studi0: Callable[..., ServedStudi0], path: str
) -> None:
    """studi0 serves the assets it carries, and says so about the rest.

    The ``/assets`` entries matter because the page's three files are
    the only ones there are: studi0 embeds them, it does not serve a
    directory, so a neighbouring path is not a file it has yet to find
    — it is a file that does not exist. ``/api/anything`` is here for
    the same reason: an unrecognised ``/api`` path is genuinely not
    found, and saying so is better than a blanket error that hides
    typos.
    """
    session = launch_studi0()
    status, content_type, body = session.get(path)

    assert status == 404
    assert content_type == "application/json; charset=utf-8"
    document = json.loads(body.decode("utf-8"))
    assert document == studi0_server.NOT_FOUND_ERROR
    assert document["error"]["code"] == "NOT_FOUND"


def test_launch_returns_zero_on_clean_shutdown(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """A shut-down studi0 exits 0 and leaves nothing bound."""
    session = launch_studi0()
    assert session.stop() == 0
    assert session.server.socket.fileno() == -1


def test_query_strings_do_not_change_the_route(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """The routing table reads the path, not the query."""
    session = launch_studi0()
    status, _, body = session.get("/?since=7")
    assert status == 200
    assert body == sh0w_assets.INDEX_HTML.encode("utf-8")


def test_project_display_name_falls_back_to_the_resolved_directory() -> None:
    """A rootless path like '.' still names a project."""
    assert studi0_server.project_display_name(Path("proj")) == "proj"
    assert studi0_server.project_display_name(Path(".")) == Path.cwd().name


def test_error_bodies_are_deterministic_bytes(tmp_path: Path) -> None:
    """Identical documents encode to identical bytes (INV-5)."""
    session = studi0_state.create_session(tmp_path)
    first = studi0_server.route_request("/api/graph", session)["body"]
    second = studi0_server.route_request("/api/graph", session)["body"]
    assert first == second
    assert json.loads(first.decode("utf-8")) == studi0_server.NOT_BUILT_ERROR


def test_the_page_carries_nothing_from_the_project_tree(tmp_path: Path) -> None:
    """Nothing about the viewed project is templated into the page.

    A project directory can be named anything at all, including
    ``<script>alert(1)</script>``. studi0 never renders that name — or
    any other thing it read off the filesystem — into the document: the
    page it serves is the page the build embedded, byte for byte, and
    everything it displays it fetches from the graph API and builds as
    DOM text. There is no template step here to get wrong.
    """
    hostile = tmp_path / "<script>alert(1)</script>"
    session = studi0_state.create_session(hostile)
    body = studi0_server.route_request("/", session)["body"]

    assert body == sh0w_assets.INDEX_HTML.encode("utf-8")
    assert b"<script>alert(1)</script>" not in body
