"""The telemetry hook is invisible to agents — proven over real stdio.

Pilot-01 memo §6: ``create_server`` wraps every served tool, resource,
and prompt in :func:`s0ma_mcp._telemetry_wrap`, env-gated by
``S0MA_MCP_TELEMETRY`` (default off = the provider is returned
untouched) with a JSONL file sink (``S0MA_MCP_TELEMETRY_SINK``; never
stdout — stdio transport). The hook is deliberately UNREGISTERED in the
self-model (a cataloged component would change ``describe_server`` /
``s0ma://self/model`` payloads — the exact visibility the hook must not
have); ``test_components.py``'s handwritten-module census still passes
because the hook lives in the one permitted bootstrap module.

This smoke test pins the invisibility invariant end to end, the way an
agent actually sees the server: spawn the console-script entry point
twice over stdio — flag off vs flag on — drive both through an
identical canned JSON-RPC session (initialize, the three list calls, a
tool call that succeeds, a tool call that errors structurally, a guide
resource read, and a read of the new s0ma://project/runbook resource),
and assert the response BYTES are identical. Then assert the sink exists
(well-formed, expected keys including the self-describing `telemetry_schema`
marker on every record and the derived `counters`, the teaching-signal
resource-read record present) only in the flag-on run, and that the
batch-01a P2 `runbook_read` counter appears in the `counters` field — and
nowhere in the wire responses. The remaining per-tag counter logic is
unit-tested in test_telemetry_counters.py; the schema marker's contract
value is pinned there too (M3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from s0ma_mcp import _TELEMETRY_SCHEMA

pytest.importorskip("mcp", reason="MCP SDK not installed")

#: The body of the ``s0ma-mcp`` console script (same as test_stdio_smoke).
_ENTRY_POINT_CMD = "from s0ma_mcp import main; main()"

#: Per-response wait; generous because the first request pays the
#: server's import of the whole toolchain.
_RESPONSE_TIMEOUT_SECONDS = 60

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "mcp_surface.json"


def _canned_requests(probe_dir: Path) -> list[dict[str, Any]]:
    """The fixed JSON-RPC session both runs replay byte-identically."""
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "invisibility-probe", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "project_status",
                "arguments": {"project_root": str(probe_dir)},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            # No path and no project_root: the tool's documented
            # structured error — exercises an ok:false result without
            # touching disk.
            "params": {"name": "check", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "resources/read",
            "params": {"uri": "s0ma://guide/survival-card"},
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "resources/read",
            # The new project runbook resource (O1) — the runbook_read
            # counter derives from this read. It serves the teaching
            # variant here (the probe cwd is not a project), which is
            # deterministic across processes, so byte-identity still holds
            # (describe_server, by contrast, stamps a per-process
            # registered_at timestamp and is NOT byte-stable across runs —
            # the per-tag counter logic is unit-tested in
            # test_telemetry_counters.py instead).
            "params": {"uri": "s0ma://project/runbook"},
        },
    ]


class _LineReader:
    """Collects child-stdout lines on a thread (portable; no select())."""

    def __init__(self, stream: Any) -> None:
        self._lines: list[bytes] = []
        self._event = threading.Event()
        self._stream = stream
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        for line in self._stream:
            self._lines.append(line)
            self._event.set()

    def wait_for(self, count: int, timeout: float) -> list[bytes]:
        import time as _time

        deadline = _time.monotonic() + timeout
        while len(self._lines) < count:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            self._event.clear()
            self._event.wait(min(remaining, 0.25))
        return list(self._lines)


def _run_canned_session(
    probe_dir: Path, extra_env: dict[str, str]
) -> dict[int, bytes]:
    """Drive one server process through the canned session.

    Returns the raw response line per request id — bytes, so any
    serialization difference at all (key order, whitespace, values)
    fails the comparison.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("S0MA_MCP_TELEMETRY")
    }
    env.update(extra_env)

    proc = subprocess.Popen(
        [sys.executable, "-c", _ENTRY_POINT_CMD],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    responses: dict[int, bytes] = {}
    try:
        assert proc.stdin is not None and proc.stdout is not None
        reader = _LineReader(proc.stdout)
        expected = 0
        for request in _canned_requests(probe_dir):
            payload = json.dumps(request, separators=(",", ":")) + "\n"
            proc.stdin.write(payload.encode("utf-8"))
            proc.stdin.flush()
            if "id" not in request:
                continue  # notification: no response to wait for
            expected += 1
            lines = reader.wait_for(expected, _RESPONSE_TIMEOUT_SECONDS)
            assert len(lines) >= expected, (
                f"no response for request id {request['id']} within "
                f"{_RESPONSE_TIMEOUT_SECONDS}s; stderr:\n"
                + (proc.stderr.read().decode("utf-8", "replace")
                   if proc.stderr else "")
            )
        for line in reader.wait_for(expected, _RESPONSE_TIMEOUT_SECONDS):
            message = json.loads(line.decode("utf-8"))
            if isinstance(message.get("id"), int):
                responses[message["id"]] = line
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()
    return responses


class TestTelemetryInvisibility:
    """Flag-off and flag-on serve byte-identical responses."""

    @pytest.fixture(scope="class")
    def sessions(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> dict[str, Any]:
        """One shared off-run + on-run (spawning the server is slow)."""
        probe_dir = tmp_path_factory.mktemp("nonproject-probe")
        sink_dir = tmp_path_factory.mktemp("telemetry-sink")
        on_sink = sink_dir / "on" / "telemetry.jsonl"
        off_sink = sink_dir / "off" / "telemetry.jsonl"
        off = _run_canned_session(
            probe_dir,
            # The sink is CONFIGURED in the off run too — proving the
            # flag, not a missing path, is what keeps it unwritten.
            {"S0MA_MCP_TELEMETRY_SINK": str(off_sink)},
        )
        on = _run_canned_session(
            probe_dir,
            {
                "S0MA_MCP_TELEMETRY": "1",
                "S0MA_MCP_TELEMETRY_SINK": str(on_sink),
            },
        )
        return {
            "off": off,
            "on": on,
            "on_sink": on_sink,
            "off_sink": off_sink,
        }

    def test_all_responses_arrived(self, sessions: dict[str, Any]) -> None:
        assert set(sessions["off"]) == set(range(1, 9))
        assert set(sessions["on"]) == set(range(1, 9))

    def test_responses_byte_identical_flag_off_vs_on(
        self, sessions: dict[str, Any]
    ) -> None:
        for request_id in sorted(sessions["off"]):
            assert sessions["off"][request_id] == sessions["on"][request_id], (
                f"response for request id {request_id} differs between "
                "flag-off and flag-on runs — the telemetry hook is "
                "visible to agents"
            )

    def test_wire_tool_names_match_committed_snapshot(
        self, sessions: dict[str, Any]
    ) -> None:
        """The canned session serves the snapshot-pinned tool set."""
        wire = json.loads(sessions["off"][2].decode("utf-8"))
        wire_names = {t["name"] for t in wire["result"]["tools"]}
        committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert wire_names == {t["name"] for t in committed["tools"]}

    def test_sink_written_only_when_enabled(
        self, sessions: dict[str, Any]
    ) -> None:
        assert not sessions["off_sink"].exists(), (
            "flag-off run wrote the telemetry sink"
        )
        on_sink: Path = sessions["on_sink"]
        assert on_sink.is_file(), "flag-on run wrote no telemetry sink"
        records = [
            json.loads(line)
            for line in on_sink.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert records, "flag-on sink is empty"
        for record in records:
            assert {
                "telemetry_schema", "surface", "name",
                "ok", "ms", "size", "args", "counters",
            } <= set(record), f"telemetry record missing keys: {record}"
            assert isinstance(record["counters"], list)
        by_surface = {r["surface"] for r in records}
        # Tool calls and the teaching-signal resource read both logged.
        assert "tool" in by_surface
        assert "resource" in by_surface
        assert any(
            r["surface"] == "resource"
            and r["name"] == "s0ma://guide/survival-card"
            for r in records
        )
        tool_records = {r["name"]: r for r in records if r["surface"] == "tool"}
        assert tool_records["project_status"]["ok"] is True
        # check with no arguments returns a STRUCTURED error (ok: true at
        # the provider boundary — the dict came back, no exception).
        assert "check" in tool_records

    def test_schema_marker_on_every_record_including_zero_counter(
        self, sessions: dict[str, Any]
    ) -> None:
        """Every JSONL record self-describes with the schema marker (M3).

        The marker leads every record — including the zero-counter events
        (an ordinary tool call, a non-runbook resource read) — so a
        consumer keys on ``telemetry_schema`` instead of shape-sniffing.
        It lives only in the sink: the byte-identity test above proves the
        wire responses are identical flag-off vs flag-on, so the marker
        leaks into nothing the agent receives.
        """
        on_sink: Path = sessions["on_sink"]
        records = [
            json.loads(line)
            for line in on_sink.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert records, "flag-on sink is empty"
        assert all(
            record.get("telemetry_schema") == _TELEMETRY_SCHEMA
            for record in records
        ), "a telemetry record is missing the schema marker"
        # The clause that matters: the marker rides zero-counter records
        # too, not only the tagged ones (the canned session logs several
        # counter-free calls — project_status, the survival-card read).
        zero_counter = [record for record in records if record["counters"] == []]
        assert zero_counter, "expected at least one zero-counter record"
        assert all(
            record["telemetry_schema"] == _TELEMETRY_SCHEMA
            for record in zero_counter
        )

    def test_runbook_read_counter_present_only_in_the_sink(
        self, sessions: dict[str, Any]
    ) -> None:
        """The `runbook_read` counter lands in the JSONL — and nowhere else.

        The canned session reads the new s0ma://project/runbook resource;
        the counter lives in the sink's `counters` field only. The
        byte-identity test above proves the wire responses are identical
        flag-off vs flag-on, so no counter leaks into anything the agent
        receives. The full per-tag counter matrix (inline_rule_impression,
        refused_overwrite, drift_shown) is unit-tested against
        `_telemetry_counters` in test_telemetry_counters.py — the wrapper
        routes every surface through that one helper, so proving the
        runbook read reaches the sink proves the wiring for all of them.
        """
        on_sink: Path = sessions["on_sink"]
        records = [
            json.loads(line)
            for line in on_sink.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        runbook_reads = [
            r for r in records
            if r["surface"] == "resource"
            and r["name"] == "s0ma://project/runbook"
        ]
        assert runbook_reads, "runbook resource read not logged"
        assert all("runbook_read" in r["counters"] for r in runbook_reads)
        # The survival-card guide read carries NO counter (it is not the
        # runbook) — the tag is specific, not blanket-on-every-resource.
        survival = [
            r for r in records
            if r["name"] == "s0ma://guide/survival-card"
        ]
        assert survival and all(r["counters"] == [] for r in survival)
