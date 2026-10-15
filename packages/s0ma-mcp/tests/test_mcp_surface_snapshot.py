"""Schema snapshot of the served MCP surface (selfhost plan SH-M3, D-5).

The committed snapshot (``tests/snapshots/mcp_surface.json``) pins the
complete client-visible surface of ``create_server()`` — every tool's
name, description, input/output JSON schema, and ``ToolAnnotations``
(FR-MCP-8), every resource's URI/name/description/MIME type, and every
prompt's name/title/description/argument schema — captured through the
in-process server exactly as an MCP client would see it.

It was generated from the PRE-conversion (handwritten ``tools.py``)
surface immediately before SH-M3 converted the tools to ``.s0ma``, so
it is the behavioral-parity contract for the conversion (plan D-5: the
conversion must be behavior-invisible to MCP clients) and the standing
drift gate thereafter: any change to a served name, schema, annotation
hint, or description fails here and must be reviewed as a deliberate
product decision, committed together with the regenerated snapshot.

Regenerating after a DELIBERATE surface change::

    S0MA_MCP_UPDATE_SURFACE_SNAPSHOT=1 uv run pytest \
        packages/s0ma-mcp/tests/test_mcp_surface_snapshot.py

then review and commit the diff (the test skips on the regenerating
run; the next plain run must pass).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma_mcp import create_server

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "mcp_surface.json"

_UPDATE_ENV = "S0MA_MCP_UPDATE_SURFACE_SNAPSHOT"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _served_surface_document() -> dict[str, Any]:
    """The complete client-visible surface as one JSON-compatible document.

    Everything is serialized through the SDK's own pydantic
    ``model_dump(mode="json")`` so unset-vs-set annotation hints, schema
    structure, and optional fields are pinned exactly (``None`` means
    "hint deliberately unset" and MUST stay that way — the conditional
    ``ToolAnnotations`` hints are meaningful only on mutating tools).
    """
    server = create_server()
    tools = sorted(_run(server.list_tools()), key=lambda t: str(t.name))
    resources = sorted(_run(server.list_resources()), key=lambda r: str(r.uri))
    prompts = sorted(_run(server.list_prompts()), key=lambda p: str(p.name))
    return {
        "tools": [t.model_dump(mode="json") for t in tools],
        "resources": [r.model_dump(mode="json") for r in resources],
        "prompts": [p.model_dump(mode="json") for p in prompts],
    }


def _render(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


class TestMcpSurfaceSnapshot:
    """The served surface equals the committed snapshot, byte for byte."""

    def test_snapshot_file_is_committed(self) -> None:
        assert SNAPSHOT_PATH.is_file(), (
            f"missing committed snapshot {SNAPSHOT_PATH} — regenerate via "
            f"{_UPDATE_ENV}=1 (see module docstring) and commit it"
        )

    def test_served_surface_matches_snapshot(self) -> None:
        document = _served_surface_document()
        if os.environ.get(_UPDATE_ENV):
            SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_PATH.write_text(_render(document), encoding="utf-8")
            pytest.skip(
                "surface snapshot regenerated — review the diff, commit it, "
                "and re-run without the env var"
            )
        committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert document == committed, (
            "served MCP surface drifted from the committed schema snapshot "
            "(names/schemas/annotations/descriptions). If the change is "
            f"deliberate, regenerate via {_UPDATE_ENV}=1 and commit the "
            "diff; if not, you changed the client-visible surface by "
            "accident (plan D-5)."
        )

    def test_snapshot_covers_every_surface_kind(self) -> None:
        """The snapshot cannot silently go empty or lose a surface class."""
        committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert len(committed["tools"]) >= 9
        assert len(committed["resources"]) >= 8
        assert len(committed["prompts"]) >= 3
        for tool in committed["tools"]:
            assert tool["annotations"] is not None, (
                f"tool '{tool['name']}' snapshot carries no annotations"
            )

    def test_adopt_description_is_the_only_new_required_semantic_argument(self) -> None:
        """M3A triage: intent is required; invocation options stay ordinary."""

        committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        adopt = next(tool for tool in committed["tools"] if tool["name"] == "adopt_file")
        assert adopt["inputSchema"]["required"] == [
            "project_root", "path", "description"
        ]
        # Optional mode/timeouts on unrelated tools remain invocation policy,
        # not semantic-state fields accidentally made mandatory by M3A.
        verify_host = next(
            tool for tool in committed["tools"] if tool["name"] == "verify_host"
        )
        assert verify_host["inputSchema"]["required"] == ["project_root"]
