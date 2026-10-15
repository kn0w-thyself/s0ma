"""Shared harness for the studi0 package's tests.

Two things live here because more than one test module needs them and a
second copy of either would be a second thing to keep true:

* **A real studi0, on a real socket.** :func:`launch_studi0` runs
  :func:`s0ma_studi0.launch` on a background thread, hands back the
  server it actually bound, and always shuts it down. Nothing here
  stubs the HTTP layer — a viewer that is only ever tested through its
  own functions has not been tested as a viewer.
* **A real s0ma project to view.** The dsl's ``golden_project`` fixture
  is staged into a temporary directory as a genuine ``[tool.s0ma]``
  project and built, which is the only way to get honest build
  artifacts, a real manifest, and therefore real freshness.

Waits are event-based or condition-based, never fixed sleeps:
:func:`wait_until` polls a predicate up to a generous ceiling, and the
launch handoff is a queue. Windows CI is slow, and a sleep-tuned suite
is a flaky one.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from s0ma_studi0 import launch, studi0_server

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from http.server import ThreadingHTTPServer

#: Generous, because Windows CI is slow — these bound a hang, they are
#: not a tuning knob any assertion depends on.
STARTUP_TIMEOUT = 30.0
REQUEST_TIMEOUT = 30.0
JOIN_TIMEOUT = 30.0

#: Ceiling for "the watch has noticed and republished". The watch polls
#: every 750 ms, so this is many ticks' worth of slack.
CHANGE_TIMEOUT = 30.0

#: How often a condition is re-checked while waiting. Short enough that
#: a fast machine is not held up, long enough not to spin a core.
CHECK_INTERVAL = 0.05

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------


def wait_until(
    condition: Callable[[], _T | None],
    *,
    what: str,
    timeout: float = CHANGE_TIMEOUT,
) -> _T:
    """Poll *condition* until it returns something, or fail saying what.

    The studi0 watch notices changes by looking at the filesystem, so
    there is no event a test could wait on from the outside — the
    honest equivalent is to ask repeatedly until the answer changes,
    with a ceiling that only ever fires on a real hang.

    Args:
        condition: Returns ``None`` while the thing has not happened,
            and the value of interest once it has.
        what: Named in the failure message, so a timeout reads as a
            statement about the system rather than about the clock.
        timeout: Seconds to keep asking.

    Returns:
        Whatever *condition* first returned that was not ``None``.
    """
    deadline = time.monotonic() + timeout
    while True:
        result = condition()
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what}")
        time.sleep(CHECK_INTERVAL)


# ---------------------------------------------------------------------------
# A built golden project to view
# ---------------------------------------------------------------------------

#: The dsl's multi-module fixture project — the same one M1's
#: graph-export tests build, so both sides of the graph contract are
#: exercised against identical source.
GOLDEN_PROJECT_DIR = (
    Path(__file__).resolve().parents[2]
    / "s0ma-dsl"
    / "tests"
    / "fixtures"
    / "valid"
    / "golden_project"
)

#: A [tool.s0ma] table for the staged copy. The fixture ships bare
#: ``.s0ma`` files; staging it as a real project is what gives the build
#: a manifest, and therefore gives studi0 something to judge freshness
#: against.
STAGED_PYPROJECT = """[project]
name = "golden_project"
version = "0.0.1"

[tool.s0ma]
source_roots = ["src"]
test_roots = ["tests"]
build_dir = "golden_project_build"
bootstrap_files = []
"""

#: Where a staged project's build artifacts land, relative to its root.
BUILD_DIR_NAME = "golden_project_build"

#: A module of the staged project a test may edit to go stale.
PROBE_MODULE = "task_service"


def build_project(root: Path) -> None:
    """Build the staged project at *root* in place."""
    from s0ma_dsl.cli.main import EXIT_SUCCESS, S0maCLI

    rc = S0maCLI().run([
        "--project-root", str(root),
        "build", str(root),
        "--mode", "dev",
        "--no-cache",
    ])
    assert rc == EXIT_SUCCESS, f"fixture build failed for {root}"


def stage_project(root: Path) -> Path:
    """Stage the golden fixture at *root* as a real project, and build it."""
    if not GOLDEN_PROJECT_DIR.is_dir():
        pytest.skip(
            "the dsl's golden_project fixture is not present "
            "(these tests need a repo checkout, not an installed wheel)"
        )
    shutil.copytree(GOLDEN_PROJECT_DIR, root / "src")
    (root / "pyproject.toml").write_text(
        STAGED_PYPROJECT, encoding="utf-8", newline="\n"
    )
    build_project(root)
    return root


def touch_source(root: Path, module: str = PROBE_MODULE) -> None:
    """Edit a module's source so it no longer hashes to what was built.

    A trailing comment is the smallest honest edit: the source hash
    moves, so the build really is stale, while the declarations — and
    therefore the node set — are untouched. That separation is what
    lets a test assert "stale, and the graph did not change".
    """
    source = root / "src" / f"{module}.s0ma"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# studi0 staleness probe\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture(scope="module")
def built_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A staged, built golden project shared by read-only tests."""
    return stage_project(tmp_path_factory.mktemp("studi0_built") / "project")


@pytest.fixture()
def mutable_project(tmp_path: Path) -> Path:
    """A staged, built golden project a single test may edit."""
    return stage_project(tmp_path / "project")


# ---------------------------------------------------------------------------
# A running studi0
# ---------------------------------------------------------------------------


class ServedStudi0:
    """A studi0 launched on a background thread, and its shutdown."""

    def __init__(
        self,
        server: ThreadingHTTPServer,
        thread: threading.Thread,
        exit_codes: list[int],
        project_root: Path,
    ) -> None:
        self.server = server
        self.thread = thread
        self.exit_codes = exit_codes
        self.project_root = project_root
        address = studi0_server.bound_address(server)
        self.host: str = address["host"]
        self.port: int = address["port"]
        self.url = f"http://{self.host}:{self.port}/"
        self._stopped = False

    def get(self, path: str) -> tuple[int, str, bytes]:
        """GET one path; return (status, content type, body bytes).

        A 404/500 is an answer, not a failure — studi0 states what it
        cannot serve — so the error responses are read like any other.
        """
        target = f"http://{self.host}:{self.port}{path}"
        try:
            with urlopen(target, timeout=REQUEST_TIMEOUT) as response:
                return (
                    int(response.status),
                    str(response.headers.get("Content-Type", "")),
                    bytes(response.read()),
                )
        except HTTPError as error:
            body = bytes(error.read())
            content_type = str(error.headers.get("Content-Type", ""))
            error.close()
            return int(error.code), content_type, body

    def header(self, path: str, name: str) -> str:
        """One response header for *path*, read off a real response."""
        target = f"http://{self.host}:{self.port}{path}"
        try:
            with urlopen(target, timeout=REQUEST_TIMEOUT) as response:
                return str(response.headers.get(name, ""))
        except HTTPError as error:
            value = str(error.headers.get(name, ""))
            error.close()
            return value

    def json(self, path: str) -> dict[str, Any]:
        """GET one path and decode its JSON body."""
        _, _, body = self.get(path)
        document: dict[str, Any] = json.loads(body.decode("utf-8"))
        return document

    def stop(self) -> int:
        """Shut the server down from this thread; return launch's exit code."""
        if not self._stopped:
            self._stopped = True
            self.server.shutdown()
            self.thread.join(timeout=JOIN_TIMEOUT)
        assert not self.thread.is_alive(), "studi0 did not shut down"
        assert self.exit_codes, "launch() returned no exit code"
        return self.exit_codes[0]


class BrowserSpy:
    """Stands in for ``webbrowser.open``: records, never opens.

    ``launch()`` opens the browser on its own thread, so the positive
    assertion waits on :attr:`opened` (an event, not a sleep); the
    negative assertion is made after the launch thread has finished,
    where "no call yet" and "no call at all" cannot be confused.
    """

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.opened = threading.Event()

    def record(self, url: str, *args: object, **kwargs: object) -> bool:
        self.urls.append(url)
        self.opened.set()
        return True

    def wait(self, timeout: float = STARTUP_TIMEOUT) -> bool:
        return self.opened.wait(timeout)


@pytest.fixture()
def browser(monkeypatch: pytest.MonkeyPatch) -> BrowserSpy:
    """Record ``webbrowser.open`` calls instead of opening a browser."""
    spy = BrowserSpy()
    monkeypatch.setattr(webbrowser, "open", spy.record)
    return spy


@pytest.fixture()
def launch_studi0(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    browser: BrowserSpy,
) -> Iterator[Callable[..., ServedStudi0]]:
    """Factory: run ``launch()`` on a thread and always shut it down.

    The real ``create_server`` is wrapped so the test can hold the very
    server ``launch()`` built — the handle it needs to stop it — without
    ``launch()`` growing a test-only return value.
    """
    real_create_server = studi0_server.create_server
    built: queue.Queue[ThreadingHTTPServer] = queue.Queue()

    def _capturing_create_server(
        project_root: Path,
        port: int = 0,
        session: Any = None,
    ) -> ThreadingHTTPServer:
        server = real_create_server(project_root, port, session)
        built.put(server)
        return server

    monkeypatch.setattr(studi0_server, "create_server", _capturing_create_server)

    sessions: list[ServedStudi0] = []

    def _launch(
        project_root: Path | None = None,
        *,
        port: int = 0,
        open_browser: bool = False,
    ) -> ServedStudi0:
        root = tmp_path / "demo-project" if project_root is None else project_root
        root.mkdir(parents=True, exist_ok=True)
        exit_codes: list[int] = []

        def _run() -> None:
            exit_codes.append(
                launch(root, port=port, open_browser=open_browser)
            )

        thread = threading.Thread(target=_run, name="studi0-test", daemon=True)
        thread.start()
        # Event-based handoff: create_server has returned, so the socket
        # is bound and listening before any request is made.
        server = built.get(timeout=STARTUP_TIMEOUT)
        session = ServedStudi0(server, thread, exit_codes, root)
        sessions.append(session)
        return session

    yield _launch

    for session in sessions:
        session.stop()
