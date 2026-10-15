"""Contract tests for the studi0 watch and the session it keeps current.

These drive the session and the watch directly — no HTTP — because the
properties at stake are about *when studi0 changes its mind*, and the
server is only the messenger:

* a reading is taken before anything is served, so nothing is ever
  served from an empty session;
* ``seq`` advances on evidence and on nothing else;
* a build caught half-written costs one tick, never the watch — the
  last good reading keeps being served, and the failure is described
  once rather than four times a second;
* a stopped watch is really stopped.

Waiting is done on real ticks, counted through a wrapped ``poll_once``,
so "several polls later" is an observed fact rather than a sleep long
enough to probably be true.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from conftest import BUILD_DIR_NAME, PROBE_MODULE, touch_source, wait_until

from s0ma_studi0 import studi0_state, studi0_watch

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

#: The build artifact a test corrupts to imitate a build landing while
#: studi0 is mid-read.
PROBE_IR = f"{PROBE_MODULE}.s0ma.json"


class Watch:
    """A running watch, its session, and a count of the ticks it has taken."""

    def __init__(self, session: studi0_state.Studi0Session) -> None:
        self.session = session
        self.ticks = 0
        self._lock = threading.Lock()
        self.watcher: studi0_watch.Studi0Watcher | None = None

    def count_tick(self) -> None:
        with self._lock:
            self.ticks += 1

    def tick_count(self) -> int:
        with self._lock:
            return self.ticks

    def wait_for_ticks(self, count: int) -> None:
        """Wait until *count* further polls have actually happened."""
        target = self.tick_count() + count
        wait_until(
            lambda: True if self.tick_count() >= target else None,
            what=f"{count} more watch tick(s)",
        )

    def snapshot(self) -> studi0_state.Studi0Snapshot:
        return studi0_state.read_snapshot(self.session)


@pytest.fixture()
def watching(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[Path], Watch]]:
    """Factory: start a watch on a project, counting ticks; always stop it."""
    real_poll_once = studi0_watch.poll_once
    started: list[Watch] = []

    def _start(project_root: Path) -> Watch:
        watch = Watch(studi0_state.create_session(project_root))

        def _counting_poll(watcher: studi0_watch.Studi0Watcher) -> bool:
            try:
                return bool(real_poll_once(watcher))
            finally:
                watch.count_tick()

        # Both the first reading and every later one go through this,
        # because start_watcher and the loop body resolve poll_once as
        # a module global at call time.
        monkeypatch.setattr(studi0_watch, "poll_once", _counting_poll)
        watch.watcher = studi0_watch.start_watcher(watch.session)
        started.append(watch)
        return watch

    yield _start

    for watch in started:
        if watch.watcher is not None:
            studi0_watch.stop_watcher(watch.watcher)


# ---------------------------------------------------------------------------
# Starting and stopping
# ---------------------------------------------------------------------------


def test_the_first_reading_lands_before_start_returns(
    watching: Callable[[Path], Watch], built_project: Path
) -> None:
    """A served studi0 is never serving from an unread session."""
    watch = watching(built_project)
    snapshot = watch.snapshot()

    assert watch.tick_count() >= 1
    assert snapshot.seq == 1
    assert snapshot.build_status == "fresh"
    assert snapshot.graph is not None
    assert snapshot.graph["nodes"]


def test_the_watch_thread_is_a_daemon(
    watching: Callable[[Path], Watch], built_project: Path
) -> None:
    """A viewer must never be why a process refuses to exit."""
    watch = watching(built_project)
    assert watch.watcher is not None
    assert watch.watcher.thread is not None
    assert watch.watcher.thread.daemon is True
    assert watch.watcher.thread.is_alive()


def test_a_stopped_watch_really_stops(
    watching: Callable[[Path], Watch], mutable_project: Path
) -> None:
    """After stop_watcher nothing is read — until someone asks explicitly.

    The explicit refresh at the end is what makes this a statement about
    the watch rather than about the edit: the change was real, and only
    the watch's absence kept it unseen.
    """
    watch = watching(mutable_project)
    assert watch.watcher is not None
    studi0_watch.stop_watcher(watch.watcher)
    assert watch.watcher.thread is not None
    assert not watch.watcher.thread.is_alive()

    before = watch.snapshot().seq
    touch_source(mutable_project)
    assert watch.snapshot().seq == before

    assert studi0_state.refresh_session(watch.session) is True
    assert watch.snapshot().seq == before + 1
    assert watch.snapshot().build_status == "stale"


def test_stop_is_safe_to_call_twice(
    watching: Callable[[Path], Watch], built_project: Path
) -> None:
    """Shutting down twice is a no-op, not an error."""
    watch = watching(built_project)
    assert watch.watcher is not None
    studi0_watch.stop_watcher(watch.watcher)
    studi0_watch.stop_watcher(watch.watcher)


# ---------------------------------------------------------------------------
# seq advances on evidence only
# ---------------------------------------------------------------------------


def test_a_quiet_project_polls_without_advancing_seq(
    watching: Callable[[Path], Watch], built_project: Path
) -> None:
    """Ticks are not changes: many polls, one reading."""
    watch = watching(built_project)
    before = watch.snapshot()

    watch.wait_for_ticks(3)

    after = watch.snapshot()
    assert after.seq == before.seq == 1
    assert after.graph == before.graph


def test_an_edited_source_advances_seq_once(
    watching: Callable[[Path], Watch], mutable_project: Path
) -> None:
    """One change, one advance — and the graph itself is untouched."""
    watch = watching(mutable_project)
    before = watch.snapshot()

    touch_source(mutable_project)
    stale = wait_until(
        lambda: (
            watch.snapshot()
            if watch.snapshot().build_status == "stale"
            else None
        ),
        what="the watch to notice the edited source",
    )

    assert stale.seq == before.seq + 1
    assert stale.stale_modules == (PROBE_MODULE,)
    assert before.graph is not None
    assert stale.graph is not None
    assert stale.graph["nodes"] == before.graph["nodes"]

    # And it stays at one advance while nothing else happens.
    watch.wait_for_ticks(3)
    assert watch.snapshot().seq == stale.seq


# ---------------------------------------------------------------------------
# Surviving a build that lands mid-read
# ---------------------------------------------------------------------------


def test_a_half_written_artifact_keeps_the_last_good_reading(
    watching: Callable[[Path], Watch],
    mutable_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unreadable artifact costs one tick, never the watch.

    This is the mid-build case: a build is rewriting the IR and studi0
    looks at exactly the wrong moment. The right answer is to keep
    showing what was last true and look again.
    """
    watch = watching(mutable_project)
    good = watch.snapshot()
    artifact = mutable_project / BUILD_DIR_NAME / PROBE_IR
    intact = artifact.read_bytes()

    artifact.write_bytes(b"{ this is a build in progress, not JSON")
    wait_until(
        lambda: (
            True
            if watch.watcher is not None and watch.watcher.reported_failures
            else None
        ),
        what="the watch to notice the unreadable artifact",
    )
    watch.wait_for_ticks(2)

    assert watch.watcher is not None
    assert watch.watcher.thread is not None
    assert watch.watcher.thread.is_alive(), "the watch died on a bad read"
    during = watch.snapshot()
    assert during.seq == good.seq
    assert during.graph == good.graph

    artifact.write_bytes(intact)
    watch.wait_for_ticks(2)

    after = watch.snapshot()
    # The file is byte-identical again, so the reading is too — and an
    # identical reading is not a change, so seq must not have moved.
    assert after.graph == good.graph
    assert after.seq == good.seq
    assert after.build_status == "fresh"

    assert "Traceback" not in capsys.readouterr().err


def test_a_repeated_failure_is_reported_once(
    watching: Callable[[Path], Watch],
    mutable_project: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A persistently broken project is described once, not per tick."""
    watch = watching(mutable_project)
    artifact = mutable_project / BUILD_DIR_NAME / PROBE_IR
    artifact.write_bytes(b"{ not JSON at all")

    wait_until(
        lambda: (
            True
            if watch.watcher is not None and watch.watcher.reported_failures
            else None
        ),
        what="the first failure report",
    )
    watch.wait_for_ticks(4)

    assert watch.watcher is not None
    assert len(watch.watcher.reported_failures) == 1
    reports = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("studi0: could not read")
    ]
    assert len(reports) == 1, f"expected one report, got {reports!r}"


def test_an_unreadable_manifest_makes_freshness_unknowable(
    watching: Callable[[Path], Watch], mutable_project: Path
) -> None:
    """A corrupt manifest is not a crash — it is a loss of evidence.

    The IR is still readable, so the graph keeps being served; what is
    gone is the recorded source hashes, and with them any right to
    claim the build is fresh. Note this path never raises: the dsl's
    export reports the missing evidence rather than throwing, so the
    watch has nothing to report to stderr.
    """
    watch = watching(mutable_project)
    good = watch.snapshot()
    manifest = mutable_project / BUILD_DIR_NAME / "build.s0ma.json"
    intact = manifest.read_bytes()

    manifest.write_bytes(b"{ half a manifest")
    missing = wait_until(
        lambda: (
            watch.snapshot()
            if watch.snapshot().build_status == "missing"
            else None
        ),
        what="freshness to become unknowable",
    )

    assert missing.seq == good.seq + 1
    assert missing.stale_modules == ()
    assert missing.graph is not None
    assert good.graph is not None
    assert missing.graph["nodes"] == good.graph["nodes"]
    assert watch.watcher is not None
    assert watch.watcher.reported_failures == set()

    manifest.write_bytes(intact)
    recovered = wait_until(
        lambda: (
            watch.snapshot()
            if watch.snapshot().build_status == "fresh"
            else None
        ),
        what="freshness to be knowable again",
    )
    assert recovered.seq == missing.seq + 1
    assert recovered.graph == good.graph


def test_poll_once_never_raises(
    mutable_project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whatever a refresh does, the tick returns — the thread cannot die."""
    session = studi0_state.create_session(mutable_project)
    watcher = studi0_watch.Studi0Watcher(session=session)

    def _explode(_: studi0_state.Studi0Session) -> bool:
        raise RuntimeError("the disk went away")

    original = studi0_watch.refresh_session
    studi0_watch.refresh_session = _explode  # type: ignore[assignment]
    try:
        assert studi0_watch.poll_once(watcher) is False
        assert studi0_watch.poll_once(watcher) is False
    finally:
        studi0_watch.refresh_session = original  # type: ignore[assignment]

    assert watcher.reported_failures == {"RuntimeError: the disk went away"}
    reports = [
        line
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("studi0: could not read")
    ]
    assert len(reports) == 1


# ---------------------------------------------------------------------------
# The session's own rules
# ---------------------------------------------------------------------------


def test_creating_a_session_reads_nothing(built_project: Path) -> None:
    """Opening a session touches no files, so binding can never be blocked."""
    session = studi0_state.create_session(built_project)
    snapshot = studi0_state.read_snapshot(session)

    assert snapshot.seq == 1
    assert snapshot.graph is None
    assert snapshot.build_status == "missing"
    assert snapshot.stale_modules == ()
    assert session.seeded is False


def test_the_first_publish_does_not_advance_seq(built_project: Path) -> None:
    """A first reading is seq 1, so a client's first answer never skips."""
    session = studi0_state.create_session(built_project)

    assert studi0_state.refresh_session(session) is True
    assert studi0_state.read_snapshot(session).seq == 1
    assert studi0_state.read_snapshot(session).build_status == "fresh"

    # A second identical reading is not a reading worth publishing.
    assert studi0_state.refresh_session(session) is False
    assert studi0_state.read_snapshot(session).seq == 1


def test_an_unbuilt_project_reads_as_missing(tmp_path: Path) -> None:
    """Nothing built is a fact studi0 can state, not an error it hits."""
    session = studi0_state.create_session(tmp_path / "empty")
    assert studi0_state.read_graph(tmp_path / "empty") is None

    studi0_state.refresh_session(session)
    snapshot = studi0_state.read_snapshot(session)
    assert snapshot.build_status == "missing"
    assert snapshot.graph is None
    assert studi0_state.graph_document(snapshot) is None
