"""Contract tests for the narration side channel (M11).

Two halves, both driven directly against real files rather than through
a stub, because both are about what happens to bytes on disk:

* **The presence marker.** studi0 writes exactly one file into the tree
  it is viewing — ``.s0ma/studi0/active.json`` — so the authoring MCP
  server can tell an agent that someone is watching, and so it stays
  silent when nobody is (owner decision D-11). It carries the pid and
  the port that was really bound, it is removed on a clean shutdown,
  and a studi0 never withdraws another studi0's claim.

* **The session log tail.** The agent appends narration lines; the
  watch reads whatever is complete since the last look. The properties
  that matter are the ones a naive reader gets wrong: a line caught
  mid-write is not read at all, a line that does not parse is counted
  and dropped rather than repaired, the same bytes are never read
  twice, and a log that got shorter is a different log.

Truth discipline runs through all of it: nothing read here is ever
promoted to a graph fact, and nothing studi0 could not read is ever
guessed at. What it cannot parse it counts, and says so.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from conftest import wait_until

from s0ma_studi0 import studi0_narration, studi0_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from conftest import ServedStudi0

#: The two files the feature is made of, relative to the project root.
PRESENCE = (".s0ma", "studi0", "active.json")
SESSION_LOG = (".s0ma", "studi0", "session.jsonl")


def narration(
    movement: str = "Reading the billing module",
    why: str | None = "the invoice total is wrong",
    phase: str = "orient",
    subjects: list[str] | None = None,
) -> str:
    """One well-formed narration line, without its newline."""
    record: dict[str, Any] = {
        "type": "work.narrated",
        "movement": movement,
        "why": why,
        "subjects": [] if subjects is None else subjects,
        "phase": phase,
    }
    return json.dumps(record, sort_keys=True)


def append(root: Path, *lines: str, newline: bool = True) -> None:
    """Append *lines* to the project's session log, creating it if needed."""
    path = root.joinpath(*SESSION_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + ("\n" if newline else "")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def read_log(root: Path) -> studi0_narration.NarrationLog:
    """A fresh reading of *root*'s session log, advanced once."""
    log = studi0_narration.NarrationLog()
    studi0_narration.read_narrations(log, root)
    return log


def movements(log: studi0_narration.NarrationLog) -> list[str]:
    return [str(entry["movement"]) for entry in log.entries]


def await_marker(studi0: ServedStudi0) -> dict[str, Any]:
    """The presence marker of a running studi0, once it has been written.

    ``launch()`` marks the project just after the socket is bound, and
    the harness hands the test its server the moment ``create_server``
    returns — so the two race by a hair. Waited on as a condition, like
    every other wait in this suite, rather than slept past.

    The condition tolerates the second, narrower race: the file exists
    before its JSON has landed (``write_text`` creates and then writes),
    so an empty or partial read is "not yet", not a failure.
    """
    marker = studi0.project_root.joinpath(*PRESENCE)

    def written() -> dict[str, Any] | None:
        if not marker.is_file():
            return None
        try:
            document: dict[str, Any] = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return document

    return wait_until(written, what="studi0 to mark the project as watched")


# ---------------------------------------------------------------------------
# The presence marker
# ---------------------------------------------------------------------------


def test_the_marker_lands_at_the_documented_path(tmp_path: Path) -> None:
    """The MCP server reads this exact path, so it is pinned here."""
    written = studi0_narration.write_presence(tmp_path, 51234)

    assert written == tmp_path.joinpath(*PRESENCE)
    assert written == studi0_narration.presence_path(tmp_path)
    assert written.is_file()


def test_the_marker_names_this_process_and_the_given_port(tmp_path: Path) -> None:
    record = json.loads(
        studi0_narration.write_presence(tmp_path, 51234).read_text(encoding="utf-8")
    )

    assert record == {"pid": os.getpid(), "port": 51234}


def test_the_marker_is_deterministic_bytes(tmp_path: Path) -> None:
    """Sorted keys, utf-8, one LF-terminated line, no timestamp (INV-5)."""
    first = studi0_narration.write_presence(tmp_path, 51234).read_bytes()
    second = studi0_narration.write_presence(tmp_path, 51234).read_bytes()

    assert first == second
    assert first.endswith(b"}\n")
    assert b"\r" not in first
    assert first == json.dumps(
        {"pid": os.getpid(), "port": 51234}, sort_keys=True
    ).encode("utf-8") + b"\n"


def test_the_marker_directory_is_created_when_absent(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    assert not (root / ".s0ma").exists()

    studi0_narration.write_presence(root, 1234)

    assert root.joinpath(*PRESENCE).is_file()


def test_clearing_removes_this_process_own_marker(tmp_path: Path) -> None:
    studi0_narration.write_presence(tmp_path, 51234)

    assert studi0_narration.clear_presence(tmp_path) is True
    assert not tmp_path.joinpath(*PRESENCE).exists()


def test_clearing_is_safe_when_there_is_nothing_to_clear(tmp_path: Path) -> None:
    """Called on every exit path, including ones that never marked."""
    assert studi0_narration.clear_presence(tmp_path) is False
    assert studi0_narration.clear_presence(tmp_path) is False


def test_one_studi0_never_withdraws_another_ones_claim(tmp_path: Path) -> None:
    """Two viewers can watch one project; the first to exit is not the last."""
    marker = tmp_path.joinpath(*PRESENCE)
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps({"pid": os.getpid() + 1, "port": 51234}), encoding="utf-8"
    )

    assert studi0_narration.clear_presence(tmp_path) is False
    assert marker.is_file()


def test_an_unreadable_marker_is_left_alone(tmp_path: Path) -> None:
    """What studi0 cannot read, it cannot claim — and so does not remove."""
    marker = tmp_path.joinpath(*PRESENCE)
    marker.parent.mkdir(parents=True)
    marker.write_text("not json at all", encoding="utf-8")

    assert studi0_narration.clear_presence(tmp_path) is False
    assert marker.is_file()


# ---------------------------------------------------------------------------
# The presence marker, through launch()
# ---------------------------------------------------------------------------


def test_a_served_studi0_marks_the_project_with_its_real_port(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """The marker advertises the port that was really bound, not the asked one."""
    studi0 = launch_studi0(port=0)

    record = await_marker(studi0)
    assert record["port"] == studi0.port
    assert record["pid"] == os.getpid()


def test_a_clean_shutdown_leaves_no_marker(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """The next agent to ask must not be told a dead viewer is watching."""
    studi0 = launch_studi0()
    await_marker(studi0)

    assert studi0.stop() == 0
    assert not studi0.project_root.joinpath(*PRESENCE).exists()


def test_marking_is_the_only_thing_studi0_writes(
    launch_studi0: Callable[..., ServedStudi0], tmp_path: Path
) -> None:
    """One file, in the local-state directory, and nothing else in the tree."""
    root = tmp_path / "untouched"
    root.mkdir()
    (root / "source.s0ma").write_text("module probe\n", encoding="utf-8")
    before = (root / "source.s0ma").read_bytes()

    studi0 = launch_studi0(root)
    assert studi0.stop() == 0

    assert (root / "source.s0ma").read_bytes() == before
    assert sorted(path.name for path in root.iterdir()) == [".s0ma", "source.s0ma"]


# ---------------------------------------------------------------------------
# Tailing the session log
# ---------------------------------------------------------------------------


def test_a_project_with_no_log_reads_nothing_and_never_raises(
    tmp_path: Path,
) -> None:
    """Most sessions never narrate, and studi0 has nothing to say about it."""
    log = studi0_narration.NarrationLog()

    assert studi0_narration.read_narrations(log, tmp_path) is False
    assert log.entries == []
    assert log.total == 0
    assert log.invalid == 0
    assert log.offset == 0


def test_appended_lines_arrive_in_file_order(tmp_path: Path) -> None:
    append(
        tmp_path,
        narration("First movement", phase="orient"),
        narration("Second movement", phase="author"),
        narration("Third movement", phase="verify"),
    )

    log = read_log(tmp_path)

    assert movements(log) == ["First movement", "Second movement", "Third movement"]
    assert log.total == 3
    assert log.invalid == 0


def test_a_narration_is_projected_to_the_frozen_entry_shape(tmp_path: Path) -> None:
    append(tmp_path, narration(subjects=["billing::charge_invoice"]))

    entry = read_log(tmp_path).entries[0]

    assert entry == {
        "n": 1,
        "movement": "Reading the billing module",
        "why": "the invoice total is wrong",
        "subjects": ["billing::charge_invoice"],
        "phase": "orient",
    }


def test_an_omitted_why_is_carried_as_absent_not_invented(tmp_path: Path) -> None:
    append(tmp_path, json.dumps({
        "type": "work.narrated",
        "movement": "Orienting",
        "phase": "orient",
    }))

    entry = read_log(tmp_path).entries[0]

    assert entry["why"] is None
    assert entry["subjects"] == []


def test_only_complete_lines_are_read(tmp_path: Path) -> None:
    """A line caught mid-write costs one tick, never a half-shown movement."""
    append(tmp_path, narration("First movement"))
    append(tmp_path, '{"type": "work.narrated", "movement": "Half a mov', newline=False)

    log = read_log(tmp_path)
    assert movements(log) == ["First movement"]
    assert log.invalid == 0

    # The writer finishes the line; the next tick picks it up whole.
    append(tmp_path, 'ement", "phase": "author", "why": null, "subjects": []}')
    assert studi0_narration.read_narrations(log, tmp_path) is True
    assert movements(log) == ["First movement", "Half a movement"]
    assert log.invalid == 0


def test_the_same_bytes_are_never_read_twice(tmp_path: Path) -> None:
    """The offset is what makes a tail a tail across the watch's ticks."""
    append(tmp_path, narration("First movement"))
    log = read_log(tmp_path)
    first_offset = log.offset

    assert studi0_narration.read_narrations(log, tmp_path) is False
    assert log.offset == first_offset
    assert log.total == 1

    append(tmp_path, narration("Second movement"))
    assert studi0_narration.read_narrations(log, tmp_path) is True
    assert log.offset > first_offset
    assert movements(log) == ["First movement", "Second movement"]


def test_a_shorter_log_is_a_different_log(tmp_path: Path) -> None:
    """Truncation resets the reading rather than splicing two sessions."""
    append(tmp_path, narration("From the old session"))
    log = read_log(tmp_path)
    assert log.total == 1

    path = tmp_path.joinpath(*SESSION_LOG)
    path.write_text("", encoding="utf-8", newline="\n")
    assert studi0_narration.read_narrations(log, tmp_path) is True
    assert log.entries == []
    assert log.total == 0
    assert log.offset == 0

    append(tmp_path, narration("From the new session"))
    studi0_narration.read_narrations(log, tmp_path)
    assert movements(log) == ["From the new session"]


# ---------------------------------------------------------------------------
# What is refused, and counted
# ---------------------------------------------------------------------------


def test_unparseable_and_off_schema_lines_are_counted_never_rendered(
    tmp_path: Path,
) -> None:
    """No repair, no completion, no guess — a refusal is a count."""
    append(
        tmp_path,
        "not json at all",
        "[1, 2, 3]",
        '"a bare string"',
        json.dumps({"type": "build.finished", "movement": "x", "phase": "orient"}),
        json.dumps({"type": "work.narrated", "phase": "orient"}),
        json.dumps({"type": "work.narrated", "movement": "  ", "phase": "orient"}),
        json.dumps({"type": "work.narrated", "movement": 7, "phase": "orient"}),
        json.dumps({"type": "work.narrated", "movement": "x", "phase": "sideways"}),
        json.dumps({"type": "work.narrated", "movement": "x", "phase": "Orient"}),
        json.dumps({
            "type": "work.narrated", "movement": "x", "phase": "orient", "why": 7,
        }),
        json.dumps({
            "type": "work.narrated",
            "movement": "x",
            "phase": "orient",
            "subjects": "billing::charge_invoice",
        }),
        json.dumps({
            "type": "work.narrated",
            "movement": "x",
            "phase": "orient",
            "subjects": [7],
        }),
        narration("The one good line"),
    )

    log = read_log(tmp_path)

    assert movements(log) == ["The one good line"]
    assert log.total == 1
    assert log.invalid == 12


def test_undecodable_bytes_cost_exactly_their_own_line(tmp_path: Path) -> None:
    """Each line is decoded on its own, so one bad line is one bad line."""
    path = tmp_path.joinpath(*SESSION_LOG)
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"\xff\xfe not utf-8 at all\n" + narration("Still readable").encode("utf-8")
        + b"\n"
    )

    log = read_log(tmp_path)

    assert movements(log) == ["Still readable"]
    assert log.invalid == 1


def test_blank_lines_are_not_refusals(tmp_path: Path) -> None:
    """An empty line says nothing; it is not a line studi0 failed to read."""
    append(tmp_path, narration("A movement"), "", "   ", narration("Another"))

    log = read_log(tmp_path)

    assert log.total == 2
    assert log.invalid == 0


def test_every_legal_phase_is_accepted(tmp_path: Path) -> None:
    for phase in studi0_narration.NARRATION_PHASES:
        append(tmp_path, narration(f"Movement in {phase}", phase=phase))

    log = read_log(tmp_path)

    assert [entry["phase"] for entry in log.entries] == list(
        studi0_narration.NARRATION_PHASES
    )
    assert log.invalid == 0


# ---------------------------------------------------------------------------
# The bound
# ---------------------------------------------------------------------------


def test_the_window_is_bounded_and_says_what_it_left_out(tmp_path: Path) -> None:
    """A long session is a bounded payload, never a growing one."""
    count = studi0_narration.NARRATION_WINDOW + 15
    append(tmp_path, *[narration(f"Movement {index}") for index in range(count)])

    log = read_log(tmp_path)

    assert len(log.entries) == studi0_narration.NARRATION_WINDOW
    assert log.total == count
    assert movements(log)[0] == "Movement 15"
    assert movements(log)[-1] == f"Movement {count - 1}"
    # The ordinal is the position in the SESSION, not in the window.
    assert log.entries[0]["n"] == 16
    assert log.entries[-1]["n"] == count


def test_the_snapshot_is_a_copy_taken_together(tmp_path: Path) -> None:
    append(tmp_path, narration("A movement"), "not json at all")
    log = read_log(tmp_path)

    entries, total, invalid = studi0_narration.narration_snapshot(log)
    assert total == 1
    assert invalid == 1

    entries[0]["movement"] = "tampered"
    assert log.entries[0]["movement"] == "A movement"


# ---------------------------------------------------------------------------
# Through the session: seq, and the served document
# ---------------------------------------------------------------------------


def test_a_new_narration_advances_seq(tmp_path: Path) -> None:
    """Narration is evidence of change like any other — that is why it repaints."""
    session = studi0_state.create_session(tmp_path)
    assert studi0_state.refresh_session(session) is True
    first = studi0_state.read_snapshot(session).seq

    append(tmp_path, narration("A movement"))
    assert studi0_state.refresh_session(session) is True

    snapshot = studi0_state.read_snapshot(session)
    assert snapshot.seq == first + 1
    assert snapshot.narrated == 1
    assert [entry["movement"] for entry in snapshot.narration] == ["A movement"]


def test_an_unchanged_log_never_advances_seq(tmp_path: Path) -> None:
    append(tmp_path, narration("A movement"))
    session = studi0_state.create_session(tmp_path)
    studi0_state.refresh_session(session)
    settled = studi0_state.read_snapshot(session).seq

    for _ in range(3):
        assert studi0_state.refresh_session(session) is False
    assert studi0_state.read_snapshot(session).seq == settled


def test_a_refused_line_advances_seq_too(tmp_path: Path) -> None:
    """The count of what could not be read is served, so it is news."""
    session = studi0_state.create_session(tmp_path)
    studi0_state.refresh_session(session)
    first = studi0_state.read_snapshot(session).seq

    append(tmp_path, "not json at all")
    assert studi0_state.refresh_session(session) is True

    snapshot = studi0_state.read_snapshot(session)
    assert snapshot.seq == first + 1
    assert snapshot.unreadable == 1
    assert snapshot.narration == ()


def test_the_state_document_carries_the_narration_block(tmp_path: Path) -> None:
    append(tmp_path, narration("A movement"), "not json at all")
    session = studi0_state.create_session(tmp_path)
    studi0_state.refresh_session(session)

    document = studi0_state.state_document(studi0_state.read_snapshot(session))

    assert document["narration"] == {
        "entries": [
            {
                "n": 1,
                "movement": "A movement",
                "why": "the invoice total is wrong",
                "subjects": [],
                "phase": "orient",
            }
        ],
        "total": 1,
        "invalid": 1,
    }


def test_narration_never_enters_the_graph(tmp_path: Path) -> None:
    """Self-report is carried beside canonical truth, never folded into it."""
    append(tmp_path, narration("A movement", subjects=["billing::charge_invoice"]))
    session = studi0_state.create_session(tmp_path)
    studi0_state.refresh_session(session)

    snapshot = studi0_state.read_snapshot(session)
    assert snapshot.graph is None
    assert studi0_state.graph_document(snapshot) is None


# ---------------------------------------------------------------------------
# End to end, over HTTP
# ---------------------------------------------------------------------------


def test_a_narration_reaches_the_served_state_document(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """The whole loop: an agent appends a line, the page can see it."""
    studi0 = launch_studi0()
    assert studi0.json("/api/state")["narration"]["total"] == 0

    append(studi0.project_root, narration("Wiring the invoice total contract"))

    served = wait_until(
        lambda: (
            studi0.json("/api/state")
            if studi0.json("/api/state")["narration"]["total"] == 1
            else None
        ),
        what="the narration to reach /api/state",
    )
    entry = served["narration"]["entries"][0]
    assert entry["movement"] == "Wiring the invoice total contract"
    assert served["narration"]["invalid"] == 0


def test_a_running_studi0_marks_the_project_with_a_live_pid(
    launch_studi0: Callable[..., ServedStudi0],
) -> None:
    """The pid is the half of the marker that separates live from leftover.

    The reading side (the authoring MCP server) probes this pid to tell
    a running viewer from a file an unclean shutdown left behind, so
    what is pinned here is the writing side's part of that contract: a
    marker written while studi0 is serving names a process that really
    is running — this one.
    """
    studi0 = launch_studi0()
    record = await_marker(studi0)

    assert record["pid"] == os.getpid()
    assert studi0.json("/api/state")["seq"] >= 1
