"""Smoke test for the stdio transport itself.

Every other test in this suite drives the server in-process through
FastMCP's ``call_tool()`` / ``read_resource()`` — fast and hermetic,
but none of it proves the actual product entry point (``s0ma-mcp`` →
``s0ma_mcp:main`` → ``FastMCP.run()`` on stdio) can start and serve.
This closes that gap (Windows-support plan, audit row T-4) at the
transport level, portably:

- spawn ``sys.executable -c "<the console script's exact body>"`` —
  no shell, no temp dirs, no signal module (works on Windows);
- hold the child's stdin open and silent: a healthy stdio server
  blocks reading it;
- ``wait(timeout=5)`` raising ``TimeoutExpired`` is therefore the PASS
  signal — the server came up and is serving, not crashed;
- an early exit is a startup crash: fail with the child's stderr.

Which server came up is pinned by construction, not protocol I/O: the
spawned command is the body of the ``s0ma-mcp`` console script
(``[project.scripts] s0ma-mcp = "s0ma_mcp:main"`` since the package
collapsed to its single bootstrap module, selfhost plan SH-M4), and
``main()`` runs the FR-MCP-1 ``s0ma-authoring`` server. The pre-0.7.0
script body (``s0ma_mcp.server:main``) is additionally smoked through
the runtime compatibility alias, so a stale installed shim keeps
starting (D-7). Asserting the server name over the wire would couple
this smoke to the MCP handshake; the in-process suite already covers
the served surface.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

#: The body of the ``s0ma-mcp`` console script, verbatim from
#: ``[project.scripts] s0ma-mcp = "s0ma_mcp:main"`` (SH-M4).
_ENTRY_POINT_CMD = "from s0ma_mcp import main; main()"

#: The pre-0.7.0 console-script body (``s0ma_mcp.server:main``) — kept
#: working by the bootstrap module's runtime ``s0ma_mcp.server`` alias
#: so an installed shim from an earlier version still starts (D-7).
_LEGACY_ENTRY_POINT_CMD = "from s0ma_mcp.server import main; main()"

#: How long the server must keep blocking on stdin to count as healthy.
_HEALTHY_BLOCK_SECONDS = 5

#: How long to wait for the child to die after terminate() / kill().
_REAP_SECONDS = 5


def _assert_starts_and_blocks_on_stdio(entry_point_cmd: str) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", entry_point_cmd],
        stdin=subprocess.PIPE,  # held open: the server must block on it
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        try:
            returncode = proc.wait(timeout=_HEALTHY_BLOCK_SECONDS)
        except subprocess.TimeoutExpired:
            pass  # still blocking on stdio after the window — healthy
        else:
            _, stderr = proc.communicate()  # child exited; drain pipes
            pytest.fail(
                f"stdio server exited within {_HEALTHY_BLOCK_SECONDS}s "
                f"(returncode {returncode}) instead of blocking on "
                "stdin; stderr:\n"
                + stderr.decode("utf-8", errors="replace")
            )
    finally:
        proc.terminate()  # no-op if the child already exited
        try:
            proc.wait(timeout=_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()  # terminate() did not reap — escalate
            proc.wait(timeout=_REAP_SECONDS)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


class TestStdioTransport:
    """The product entry point starts and serves on stdio — on every OS."""

    def test_server_entry_point_starts_and_blocks_on_stdio(self) -> None:
        _assert_starts_and_blocks_on_stdio(_ENTRY_POINT_CMD)

    def test_legacy_entry_point_shim_still_starts(self) -> None:
        """A stale 0.6.x console-script shim keeps working (D-7, SH-M4)."""
        _assert_starts_and_blocks_on_stdio(_LEGACY_ENTRY_POINT_CMD)
