"""Tests for the s0ma authoring MCP server factory and boundary.

Uses FastMCP's in-process ``call_tool()`` / ``read_resource()`` methods
(no transport server) — the testing pattern established by s0ma-core's
``tests/test_mcp_server.py``.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from mcp.server.fastmcp import FastMCP

from s0ma_mcp import create_server, normalize_docstring

EXPECTED_TOOLS = {
    "transpile",
    "build_project",
    "adopt_file",
    "check",
    "verify_host",
    "inspect_module",
    "project_status",
    "init_project",
    "run_example",
    "migrate_ext",
    "scaffold_module",
    "describe_server",
    "prepare_feedback",
    "submit_feedback",
    "learn_s0ma",
}

EXPECTED_RESOURCES = {
    "s0ma://guide/getting-started",
    "s0ma://guide/self-prompting",
    "s0ma://guide/survival-card",
    "s0ma://guide/system-prompt",
    "s0ma://guide/quick-reference",
    # Owner ruling 2026-09-29 (surface contract R5): the generated quick
    # reference's data twin, so an agent in somebody's project can reach
    # every reference in the form it reads best.
    "s0ma://guide/quick-reference.json",
    "s0ma://guide/patterns",
    "s0ma://guide/errors",
    "s0ma://spec/current",
    "s0ma://meta/changelog",
    "s0ma://meta/version",
    "s0ma://self/model",
    "s0ma://project/runbook",
    # F7: the documentation family, served from the packaged snapshot.
    # NOT core's s0ma://docs/user-guide family — that is the runtime
    # server a built application exposes, and this one says so.
    "s0ma://docs/index",
    "s0ma://docs/concepts",
    "s0ma://docs/journeys",
}

EXPECTED_PROMPTS = {
    "author_module",
    "diagnose_fault",
    "feedback",
    "fix_check_failures",
    "migrate_project",
}

#: FR-MCP-8 — the documented annotation matrix, mirroring the
#: ``mcp_tool_annotations`` attributes authored in s0ma_src/tools.s0ma
#: (rationale on each declaration) and the README table.
#: Tuples are (readOnlyHint, destructiveHint, idempotentHint,
#: openWorldHint); ``None`` = hint deliberately unset (the conditional
#: hints are meaningful only on mutating tools). Drift-style: a tool
#: added without a row here — or served with different hints — fails.
EXPECTED_ANNOTATIONS: dict[str, tuple[bool | None, ...]] = {
    "check": (True, None, None, False),
    "verify_host": (False, True, False, True),
    "inspect_module": (True, None, None, False),
    "describe_server": (True, None, None, False),
    "project_status": (True, None, None, False),
    "transpile": (False, False, True, False),
    "build_project": (False, False, True, False),
    # D2 (0.11.0): adoption is mutating (writes adopted.s0ma.json),
    # non-destructive (adds/refreshes a record; deletes nothing), and
    # non-idempotent since every re-adopt increments advisory churn
    # telemetry even when the content hash is unchanged.
    "adopt_file": (False, False, False, False),
    "scaffold_module": (False, False, True, False),
    "init_project": (False, False, True, False),
    "migrate_ext": (False, False, True, False),
    "run_example": (False, True, False, False),
    # FD-5 (0.14 surface budget §10.3, frozen): composing is pure, and
    # sending is mutating, non-destructive, idempotent by its
    # Idempotency-Key, and the only tool that reaches a kn0wthyself
    # service.
    "prepare_feedback": (True, None, None, False),
    "submit_feedback": (False, False, True, True),
    # F7: reads packaged data and nothing else — no project, no network,
    # no model — and one build answers one question the same way every
    # time, which is what makes the idempotent hint honest here.
    "learn_s0ma": (True, None, True, False),
}

#: The safe-to-auto-approve inner loop.
READ_ONLY_TOOLS = {
    "check",
    "inspect_module",
    "describe_server",
    "project_status",
    # FD-5: composing a feedback report writes nothing and sends nothing.
    "prepare_feedback",
    # F7: the documentation read surface reads package data only.
    "learn_s0ma",
}


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


def _call_tool(server: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool and return its structured (dict) result."""
    outcome = _run(server.call_tool(name, arguments))
    # FastMCP with convert_result=True returns (content_blocks, structured)
    # for tools with structured output; tolerate a bare dict for safety.
    if isinstance(outcome, tuple):
        _content, structured = outcome
        assert isinstance(structured, dict)
        return structured
    assert isinstance(outcome, dict)
    return outcome


@pytest.fixture(scope="module")
def server() -> FastMCP:
    return create_server()


class TestCreateServer:
    """The create_server() factory (mirrors core's factory tests)."""

    def test_creates_server_successfully(self, server: FastMCP) -> None:
        assert isinstance(server, FastMCP)

    def test_server_has_prd_mandated_name(self, server: FastMCP) -> None:
        assert server.name == "s0ma-authoring"

    def test_server_has_instructions(self, server: FastMCP) -> None:
        assert server.instructions
        assert "s0ma" in server.instructions
        assert "s0ma://guide/getting-started" in server.instructions

    def test_server_lists_all_tools(self, server: FastMCP) -> None:
        tools = _run(server.list_tools())
        assert {t.name for t in tools} == EXPECTED_TOOLS

    def test_tools_have_descriptions(self, server: FastMCP) -> None:
        for tool in _run(server.list_tools()):
            assert tool.description
            assert len(tool.description) > 40, (
                f"tool '{tool.name}' description too thin for agent use"
            )

    def test_tools_declare_structured_output(self, server: FastMCP) -> None:
        for tool in _run(server.list_tools()):
            assert tool.outputSchema is not None, (
                f"tool '{tool.name}' should return a structured dict"
            )

    def test_server_lists_all_resources(self, server: FastMCP) -> None:
        resources = _run(server.list_resources())
        assert {str(r.uri) for r in resources} == EXPECTED_RESOURCES

    def test_resources_have_descriptions(self, server: FastMCP) -> None:
        for resource in _run(server.list_resources()):
            assert resource.description

    def test_server_lists_all_prompts(self, server: FastMCP) -> None:
        prompts = _run(server.list_prompts())
        assert {p.name for p in prompts} == EXPECTED_PROMPTS

    def test_prompts_have_descriptions(self, server: FastMCP) -> None:
        for prompt in _run(server.list_prompts()):
            assert prompt.description

    def test_factory_returns_fresh_instances(self) -> None:
        assert create_server() is not create_server()


class TestToolAnnotations:
    """FR-MCP-8: every tool carries honest ToolAnnotations."""

    def test_every_tool_carries_annotations(self, server: FastMCP) -> None:
        """Drift gate: a future tool bound without annotations fails."""
        for tool in _run(server.list_tools()):
            assert tool.annotations is not None, (
                f"tool '{tool.name}' carries no ToolAnnotations — author "
                "mcp_tool_annotations attributes on its declaration (FR-MCP-8)"
            )

    def test_read_only_set_is_exactly_as_documented(
        self, server: FastMCP
    ) -> None:
        """The auto-approvable inner loop:
        check/inspect_module/describe_server/project_status."""
        read_only = {
            tool.name
            for tool in _run(server.list_tools())
            if tool.annotations is not None
            and tool.annotations.readOnlyHint is True
        }
        assert read_only == READ_ONLY_TOOLS

    def test_full_annotation_matrix(self, server: FastMCP) -> None:
        """Every served hint equals the documented matrix, tool by tool."""
        listed = {t.name: t.annotations for t in _run(server.list_tools())}
        assert set(listed) == set(EXPECTED_ANNOTATIONS), (
            "a tool was added/removed without updating the documented "
            "annotation matrix (here, s0ma_src/tools.s0ma, README)"
        )
        for name, expected in EXPECTED_ANNOTATIONS.items():
            annotations = listed[name]
            assert annotations is not None
            served = (
                annotations.readOnlyHint,
                annotations.destructiveHint,
                annotations.idempotentHint,
                annotations.openWorldHint,
            )
            assert served == expected, f"annotation drift on '{name}'"

    def test_only_explicit_host_verification_claims_open_world(
        self, server: FastMCP
    ) -> None:
        """Project imports and feedback delivery reach outside; the rest stay
        closed. ``submit_feedback`` is the only tool that speaks to a
        kn0wthyself service, and only after the user approves it (FD-5).
        """
        open_world = {
            tool.name
            for tool in _run(server.list_tools())
            if tool.annotations is not None
            and tool.annotations.openWorldHint is True
        }
        assert open_world == {"verify_host", "submit_feedback"}


class TestServedDescriptionsAreInterpreterIndependent:
    """F-M3-8: the served surface is identical bytes on every interpreter.

    FastMCP renders tool/resource/prompt descriptions from raw
    ``__doc__``, and raw ``__doc__`` is interpreter-dependent: CPython
    3.13 strips the common leading whitespace at compile time
    (python/cpython gh-81283) while 3.11/3.12 preserve the source
    indentation. ``create_server`` therefore routes every callable it
    binds through ``components.normalize_docstring``
    (``inspect.cleandoc``, PEP 257). These tests pin that on ANY single
    interpreter — the pre-3.13 raw form is simulated by assigning
    ``__doc__`` directly, so no 3.11-vs-3.13 matrix is needed locally.
    """

    #: The same docstring as 3.11/3.12 compile it (source indentation
    #: preserved, trailing indented blank line before the closing
    #: quotes) ...
    _PRE_313_RAW_DOC = (
        "One-line summary.\n"
        "\n"
        "        Args:\n"
        "            project_root: Directory to orient from (explicit; never\n"
        "                the server's cwd). Discovery walks upward from here.\n"
        "        "
    )
    #: ... and as 3.13 compiles it (common margin stripped at compile
    #: time, relative indentation and the trailing newline kept).
    _POST_313_RAW_DOC = (
        "One-line summary.\n"
        "\n"
        "Args:\n"
        "    project_root: Directory to orient from (explicit; never\n"
        "        the server's cwd). Discovery walks upward from here.\n"
    )

    def _served_description(self, raw_doc: str) -> str:
        """Serve a probe tool whose raw ``__doc__`` is ``raw_doc``.

        Binds through the exact create_server path: normalize_docstring
        first, then the FastMCP registration that reads ``__doc__``.
        """
        probe_server = FastMCP("normalization-probe")

        def probe() -> dict[str, Any]:
            return {}

        probe.__doc__ = raw_doc
        probe_server.tool(name="probe")(normalize_docstring(probe))
        (tool,) = _run(probe_server.list_tools())
        assert isinstance(tool.description, str)
        return tool.description

    def test_pre_and_post_313_raw_docstrings_serve_identical_bytes(
        self,
    ) -> None:
        """The binding layer collapses both interpreter forms to one."""
        served_pre = self._served_description(self._PRE_313_RAW_DOC)
        served_post = self._served_description(self._POST_313_RAW_DOC)
        assert served_pre == served_post
        assert served_post == inspect.cleandoc(self._POST_313_RAW_DOC)

    def test_every_served_description_is_cleandoc_normalized(
        self, server: FastMCP
    ) -> None:
        """Drift gate for factory rewrites (M4): every surface kind.

        Dropping normalize_docstring from any binding fails here on
        every interpreter — even on 3.13 a raw multi-line ``__doc__``
        keeps a trailing newline that ``cleandoc`` strips.
        """
        surfaces: list[tuple[str, str | None]] = []
        surfaces += [
            (f"tool:{t.name}", t.description)
            for t in _run(server.list_tools())
        ]
        surfaces += [
            (f"resource:{r.uri}", r.description)
            for r in _run(server.list_resources())
        ]
        surfaces += [
            (f"prompt:{p.name}", p.description)
            for p in _run(server.list_prompts())
        ]
        assert len(surfaces) >= 20
        for name, description in surfaces:
            assert description is not None, name
            assert description == inspect.cleandoc(description), (
                f"{name}: served description is not cleandoc-normalized "
                "— every callable bound in create_server must route "
                "through components.normalize_docstring (F-M3-8), or "
                "the MCP surface differs between Python 3.11/3.12 and "
                "3.13+"
            )


class TestToolBoundary:
    """Tools called through the MCP layer return {ok, ...} — never raise."""

    def test_check_round_trips_through_mcp(
        self, server: FastMCP, project: Path
    ) -> None:
        result = _call_tool(
            server,
            "check",
            {"project_root": str(project), "mode": "dev"},
        )
        assert result["ok"] is True
        assert result["diagnostics"]["summary"]["errors"] == 0

    def test_scaffold_check_transpile_loop_through_mcp(
        self, server: FastMCP, project: Path
    ) -> None:
        """The M5 acceptance loop, driven entirely over the MCP boundary."""
        scaffolded = _call_tool(
            server,
            "scaffold_module",
            {"project_root": str(project), "module_name": "LoopProbe"},
        )
        assert scaffolded["ok"] is True
        assert scaffolded["check"]["ok"] is True

        transpiled = _call_tool(
            server,
            "transpile",
            {
                "source_path": scaffolded["path"],
                "project_root": str(project),
            },
        )
        assert transpiled["ok"] is True
        assert transpiled["artifacts"]
        for artifact in transpiled["artifacts"]:
            assert Path(artifact).exists()

    def test_migrate_ext_defaults_to_dry_run_through_mcp(
        self, server: FastMCP, project: Path
    ) -> None:
        result = _call_tool(
            server, "migrate_ext", {"project_root": str(project)}
        )
        assert result["ok"] is True
        assert result["dry_run"] is True

    def test_failure_is_structured_not_raised(self, server: FastMCP) -> None:
        result = _call_tool(
            server,
            "build_project",
            {"project_root": "/nonexistent/project/root"},
        )
        assert result["ok"] is False
        assert "not a directory" in result["error"]

    def test_no_raw_traceback_crosses_the_boundary(
        self, server: FastMCP
    ) -> None:
        result = _call_tool(
            server, "inspect_module", {"project_root": "/nonexistent"}
        )
        assert result["ok"] is False
        assert "Traceback (most recent call last)" not in str(result)
