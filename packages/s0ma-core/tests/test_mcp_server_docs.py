"""Tests for the M8 documentation-subsystem MCP surface.

Covers the three new resources and one new tool added in Milestone 8:

* Resource ``s0ma://docs/registered-docs``            — registry-wide
  documentation overview (via ``SelfModelInterface.describe_docs``).
* Resource ``s0ma://model/examples-for/{component}``  — examples that
  demonstrate the named component.
* Resource ``s0ma://model/docs-for/{component}``      — docs that cover
  the named component.
* Tool ``get_examples_for(component)``                — explicit tool
  mirror of the ``examples-for`` resource, so MCP clients that cannot
  call templated resources directly can still reach the data.

Uses FastMCP's ``list_resources`` / ``list_resource_templates`` /
``read_resource`` / ``call_tool`` methods to exercise handlers
without starting a transport server.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("mcp", reason="MCP SDK not installed")

from s0ma._bootstrap import bootstrap_register
from s0ma.api.mcp_server import create_mcp_server
from s0ma.models import (
    AssertExpr,
    ComponentSpec,
    EntityRef,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _span() -> SourceSpan:
    return SourceSpan(file="src/sample.s0ma", start_line=1, end_line=20)


def _register_chat_router(registry: ComponentRegistry) -> None:
    registry.register(
        ComponentSpec(
            name="ChatRouter",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Routes chat messages to the correct handler",
        )
    )
    chat_router = EntityRef(kind="nerve", name="ChatRouter", module="nerve")
    registry.register_doc_ref(
        name="all-services",
        module="nerve",
        intent="List every service in the nerve module",
        format="markdown",
        output="docs/services.md",
        covers=[
            FilterExpr(
                target_kind="nerve",
                predicate="kind == 'service'",
                raw="kind == 'service' AND ChatRouter",
            ),
        ],
        sections=[Section(title="Services")],
        content_hash="hash-1",
        source_span=_span(),
    )
    registry.register_doc_guide(
        name="chat-routing-guide",
        module="nerve",
        intent="Explain ChatRouter behavior",
        format="markdown",
        output="docs/chat-routing.md",
        covers=[chat_router],
        asserts=[AssertExpr(expression="True", source_span=_span())],
        examples=[EntityRef(kind="example", name="hello-chat", module="nerve")],
        body="ChatRouter dispatches messages.",
        content_hash="hash-2",
        source_span=_span(),
    )
    registry.register_example(
        name="hello-chat",
        module="nerve",
        intent="Demonstrate ChatRouter dispatch",
        demonstrates=[chat_router],
        runs_in="standalone",
        body="from nerve import ChatRouter\n",
        source_span=_span(),
    )


@pytest.fixture()
def registry() -> ComponentRegistry:
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def mcp_server(registry: ComponentRegistry) -> Any:
    return create_mcp_server(registry)


def _read(server: Any, uri: str) -> str:
    contents = _run(server.read_resource(uri))
    # FastMCP returns an iterable of ReadResourceContents; pick the first.
    first = next(iter(contents))
    return str(first.content)


def _call_tool(
    server: Any, tool_name: str, arguments: dict[str, Any] | None = None
) -> str:
    content_list, _structured = _run(
        server.call_tool(tool_name, arguments or {})
    )
    return str(content_list[0].text)


# ---------------------------------------------------------------------------
# Resource: s0ma://docs/registered-docs
# ---------------------------------------------------------------------------


class TestRegisteredDocsResource:
    def test_resource_is_listed(self, mcp_server: Any) -> None:
        resources = _run(mcp_server.list_resources())
        uris = {str(r.uri) for r in resources}
        assert "s0ma://docs/registered-docs" in uris

    def test_empty_registry_returns_informative_text(
        self, mcp_server: Any
    ) -> None:
        text = _read(mcp_server, "s0ma://docs/registered-docs")
        assert "No documentation artifacts registered" in text

    def test_populated_registry_lists_all_artifacts(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        text = _read(mcp_server, "s0ma://docs/registered-docs")
        assert "# Documentation Overview" in text
        assert "all-services" in text
        assert "chat-routing-guide" in text
        assert "hello-chat" in text


# ---------------------------------------------------------------------------
# Resource: s0ma://model/examples-for/{component}
# ---------------------------------------------------------------------------


class TestExamplesForComponentResource:
    def test_resource_template_is_listed(self, mcp_server: Any) -> None:
        templates = _run(mcp_server.list_resource_templates())
        template_uris = {t.uriTemplate for t in templates}
        assert (
            "s0ma://model/examples-for/{component}" in template_uris
        )

    def test_resolves_matching_examples(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        text = _read(mcp_server, "s0ma://model/examples-for/ChatRouter")
        assert "Examples demonstrating 'ChatRouter'" in text
        assert "hello-chat" in text

    def test_reports_when_no_examples_match(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        text = _read(mcp_server, "s0ma://model/examples-for/NotACovering")
        assert "No canonical examples" in text


# ---------------------------------------------------------------------------
# Resource: s0ma://model/docs-for/{component}
# ---------------------------------------------------------------------------


class TestDocsForComponentResource:
    def test_resource_template_is_listed(self, mcp_server: Any) -> None:
        templates = _run(mcp_server.list_resource_templates())
        template_uris = {t.uriTemplate for t in templates}
        assert "s0ma://model/docs-for/{component}" in template_uris

    def test_resolves_matching_docs(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        text = _read(mcp_server, "s0ma://model/docs-for/ChatRouter")
        assert "Documentation covering 'ChatRouter'" in text
        assert "all-services" in text
        assert "chat-routing-guide" in text

    def test_reports_when_no_docs_match(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        text = _read(mcp_server, "s0ma://model/docs-for/UnknownThing")
        assert "No documentation artifacts cover 'UnknownThing'" in text


# ---------------------------------------------------------------------------
# Tool: get_examples_for
# ---------------------------------------------------------------------------


class TestGetExamplesForTool:
    def test_tool_is_listed(self, mcp_server: Any) -> None:
        tools = _run(mcp_server.list_tools())
        names = {t.name for t in tools}
        assert "get_examples_for" in names

    def test_tool_description_is_non_empty(self, mcp_server: Any) -> None:
        tools = _run(mcp_server.list_tools())
        by_name = {t.name: t for t in tools}
        assert (
            by_name["get_examples_for"].description is not None
            and len(by_name["get_examples_for"].description) > 0
        )

    def test_returns_examples_for_known_component(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        result = _call_tool(
            mcp_server, "get_examples_for", {"component": "ChatRouter"}
        )
        assert "hello-chat" in result
        assert "Examples demonstrating 'ChatRouter'" in result

    def test_returns_informative_text_when_no_match(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        result = _call_tool(
            mcp_server, "get_examples_for", {"component": "SomethingElse"}
        )
        assert "No canonical examples" in result

    def test_accepts_module_shortcut(
        self, mcp_server: Any, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        result = _call_tool(
            mcp_server,
            "get_examples_for",
            {"component": "nerve::ChatRouter"},
        )
        assert "hello-chat" in result


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


class TestServerSurfaceAfterM8:
    """The M8 additions do not remove or rename any existing surface."""

    def test_expected_tool_set_includes_old_and_new(
        self, mcp_server: Any
    ) -> None:
        tools = _run(mcp_server.list_tools())
        names = {t.name for t in tools}
        expected = {
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
            # New in M8
            "get_examples_for",
        }
        assert expected == names

    def test_expected_static_resources_include_old_and_new(
        self, mcp_server: Any
    ) -> None:
        resources = _run(mcp_server.list_resources())
        uris = {str(r.uri) for r in resources}
        expected = {
            "s0ma://docs/user-guide",
            "s0ma://docs/compliance-rules",
            "s0ma://docs/architecture",
            "s0ma://model/component-template",
            "s0ma://model/registry-summary",
            # New in M8
            "s0ma://docs/registered-docs",
        }
        assert expected.issubset(uris)

    def test_expected_resource_templates_are_listed(
        self, mcp_server: Any
    ) -> None:
        templates = _run(mcp_server.list_resource_templates())
        uris = {t.uriTemplate for t in templates}
        expected = {
            "s0ma://model/examples-for/{component}",
            "s0ma://model/docs-for/{component}",
        }
        assert expected.issubset(uris)
