"""Tests for the S0ma MCP server (Phase 3B, Milestone 10).

Tests the MCP server implementation that wraps the SelfModelInterface
for Model Context Protocol access by Claude Code, Claude Desktop,
and other MCP clients.

Uses FastMCP's ``call_tool()`` method for testing tool handlers
directly without running a transport server.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma._bootstrap import bootstrap_register
from s0ma.api.mcp_server import create_mcp_server
from s0ma.registry import ComponentRegistry


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Create a fresh registry with framework components registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def mcp_server(registry: ComponentRegistry) -> Any:
    """Create an MCP server with self-model tools."""
    return create_mcp_server(registry)


def _call_tool(server: Any, tool_name: str, arguments: dict[str, Any] | None = None) -> str:
    """Call an MCP tool and return its text output."""
    args = arguments or {}
    content_list, _structured = _run(server.call_tool(tool_name, args))
    # FastMCP returns a list of TextContent objects
    return content_list[0].text


class TestDescribeSystem:
    """Tests for the describe_system MCP tool."""

    def test_returns_system_overview(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "describe_system")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_s0ma(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "describe_system")
        assert "S0ma" in result

    def test_mentions_components(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "describe_system")
        assert "component" in result.lower()


class TestFindComponent:
    """Tests for the find_component MCP tool."""

    def test_returns_component_details(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "find_component", {"name": "ComponentRegistry"})
        assert "ComponentRegistry" in result
        assert "framework" in result.lower()

    def test_returns_intent(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "find_component", {"name": "ComponentRegistry"})
        # The intent should be in the output
        assert "registry" in result.lower() or "storing" in result.lower()

    def test_invalid_name_returns_error_message(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "find_component", {"name": "NonExistentComponent"})
        assert "not registered" in result.lower()
        # Should not raise — returns error as text for LLM consumption
        assert isinstance(result, str)


class TestCheckHealth:
    """Tests for the check_health MCP tool."""

    def test_returns_health_status(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "check_health")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_health_contains_status_info(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "check_health")
        assert "health" in result.lower() or "verif" in result.lower()


class TestExplainDependency:
    """Tests for the explain_dependency MCP tool."""

    def test_explains_valid_direct_dependency(self, mcp_server: Any) -> None:
        result = _call_tool(
            mcp_server,
            "explain_dependency",
            {"source": "ComponentDecorator", "target": "ComponentRegistry"},
        )
        assert "ComponentDecorator" in result
        assert "ComponentRegistry" in result
        # Should mention "direct" or show the dependency relationship
        assert "direct" in result.lower() or "->" in result

    def test_no_dependency_returns_message(self, mcp_server: Any) -> None:
        # ComponentSpec doesn't depend on S0maFinder
        result = _call_tool(
            mcp_server,
            "explain_dependency",
            {"source": "ComponentSpec", "target": "S0maFinder"},
        )
        assert "no dependency" in result.lower()

    def test_invalid_component_returns_error_message(self, mcp_server: Any) -> None:
        result = _call_tool(
            mcp_server,
            "explain_dependency",
            {"source": "NonExistent", "target": "ComponentRegistry"},
        )
        assert "not registered" in result.lower()


class TestSuggestFix:
    """Tests for the suggest_fix MCP tool."""

    def test_phantom_limb_suggestion(self, mcp_server: Any) -> None:
        result = _call_tool(
            mcp_server,
            "suggest_fix",
            {"anomaly_description": "Phantom limb: registry entry with no corresponding code"},
        )
        assert "phantom" in result.lower()
        assert "fix" in result.lower() or "suggest" in result.lower()

    def test_immune_response_suggestion(self, mcp_server: Any) -> None:
        result = _call_tool(
            mcp_server,
            "suggest_fix",
            {"anomaly_description": "Immune response: unregistered code detected in module X"},
        )
        assert "immune" in result.lower()
        assert "@component" in result or "register" in result.lower()

    def test_unknown_anomaly_returns_general_advice(self, mcp_server: Any) -> None:
        result = _call_tool(
            mcp_server,
            "suggest_fix",
            {"anomaly_description": "Something weird happened"},
        )
        assert "remediation" in result.lower() or "verify" in result.lower()


class TestGetImpact:
    """Tests for the get_impact MCP tool."""

    def test_returns_impact_analysis(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "get_impact", {"component": "ComponentRegistry"})
        assert isinstance(result, str)
        assert "ComponentRegistry" in result

    def test_high_impact_component(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "get_impact", {"component": "ComponentRegistry"})
        # ComponentRegistry has many dependents
        assert "dependent" in result.lower() or "impact" in result.lower()

    def test_invalid_component_returns_error(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "get_impact", {"component": "NonExistent"})
        assert "not registered" in result.lower()


class TestGetExtensionPoints:
    """Tests for the get_extension_points MCP tool."""

    def test_returns_extension_points(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "get_extension_points")
        assert isinstance(result, str)
        assert len(result) > 100  # Non-trivial output

    def test_mentions_layers(self, mcp_server: Any) -> None:
        result = _call_tool(mcp_server, "get_extension_points")
        # Should mention non-framework layers
        assert "domain" in result.lower() or "application" in result.lower()


class TestCreateMcpServer:
    """Tests for the create_mcp_server factory function."""

    def test_creates_server_successfully(self, registry: ComponentRegistry) -> None:
        from mcp.server.fastmcp import FastMCP

        server = create_mcp_server(registry)
        assert isinstance(server, FastMCP)

    def test_server_has_correct_name(self, registry: ComponentRegistry) -> None:
        server = create_mcp_server(registry)
        assert server.name == "s0ma-self-model"

    def test_server_lists_all_tools(self, mcp_server: Any) -> None:
        tools = _run(mcp_server.list_tools())
        tool_names = {t.name for t in tools}
        expected_tools = {
            "describe_system",
            "find_component",
            "check_health",
            "explain_dependency",
            "suggest_fix",
            "get_impact",
            "get_extension_points",
            "query_system",
            "learn_about_s0ma",
            "get_component_example",
            "get_compliance_checklist",
            "get_examples_for",  # M8 documentation-subsystem tool
        }
        assert expected_tools == tool_names

    def test_tools_have_descriptions(self, mcp_server: Any) -> None:
        tools = _run(mcp_server.list_tools())
        for tool in tools:
            assert tool.description is not None
            assert len(tool.description) > 0

    def test_server_works_without_optional_params(
        self, registry: ComponentRegistry
    ) -> None:
        """create_mcp_server works with only the required registry argument."""
        server = create_mcp_server(registry)
        result = _call_tool(server, "describe_system")
        assert "S0ma" in result

    def test_server_works_with_metrics_collector(
        self, registry: ComponentRegistry
    ) -> None:
        """create_mcp_server accepts an optional metrics_collector."""
        from s0ma.verifiers.interoception import MetricsCollector

        collector = MetricsCollector()
        server = create_mcp_server(registry, metrics_collector=collector)
        result = _call_tool(server, "describe_system")
        assert "S0ma" in result


class TestMcpOutputQuality:
    """Tests that MCP tools produce natural language suitable for Claude."""

    def test_all_tools_return_natural_language(self, mcp_server: Any) -> None:
        """Every tool returns text, not raw data structures."""
        tool_calls: list[tuple[str, dict[str, Any]]] = [
            ("describe_system", {}),
            ("find_component", {"name": "ComponentRegistry"}),
            ("check_health", {}),
            ("explain_dependency", {
                "source": "ComponentDecorator",
                "target": "ComponentRegistry",
            }),
            ("suggest_fix", {"anomaly_description": "phantom limb detected"}),
            ("get_impact", {"component": "ComponentRegistry"}),
            ("get_extension_points", {}),
        ]
        for tool_name, args in tool_calls:
            result = _call_tool(mcp_server, tool_name, args)
            assert isinstance(result, str), (
                f"Tool '{tool_name}' returned {type(result).__name__}, not str"
            )
            assert len(result) > 0, f"Tool '{tool_name}' returned empty string"
            # Should not contain raw Python repr
            assert "{'key'" not in result, (
                f"Tool '{tool_name}' appears to contain raw dict repr"
            )


class TestExplainDependencyChain:
    """Tests for the explain_dependency_chain analyzer function."""

    def test_direct_dependency(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        result = explain_dependency_chain(
            registry, "ComponentDecorator", "ComponentRegistry"
        )
        assert "Direct dependency" in result
        assert "ComponentDecorator" in result
        assert "ComponentRegistry" in result

    def test_no_dependency(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        result = explain_dependency_chain(
            registry, "ComponentSpec", "S0maFinder"
        )
        assert "No dependency" in result

    def test_transitive_dependency(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        # S0maFinder -> S0maLoader (direct)
        # But let's find a transitive case: ComponentDecorator -> ComponentSpec
        # ComponentDecorator depends on ComponentRegistry which depends on ComponentSpec
        result = explain_dependency_chain(
            registry, "ComponentDecorator", "ComponentSpec"
        )
        # Should show the chain: ComponentDecorator -> ComponentRegistry -> ComponentSpec
        assert "ComponentSpec" in result
        assert "ComponentDecorator" in result
        # Should mention "transitive" or show the chain
        if "Transitive" in result:
            assert "chain" in result.lower() or "->" in result

    def test_same_component(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        result = explain_dependency_chain(
            registry, "ComponentRegistry", "ComponentRegistry"
        )
        assert "same component" in result.lower()

    def test_nonexistent_source(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        with pytest.raises(Exception, match="not registered"):
            explain_dependency_chain(registry, "NonExistent", "ComponentRegistry")

    def test_nonexistent_target(self, registry: ComponentRegistry) -> None:
        from s0ma.self_model.analyzers import explain_dependency_chain

        with pytest.raises(Exception, match="not registered"):
            explain_dependency_chain(registry, "ComponentRegistry", "NonExistent")
