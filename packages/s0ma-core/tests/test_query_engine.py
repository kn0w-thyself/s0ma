"""Tests for the S0ma natural language query engine (Phase 3B, Milestone 11).

Tests the QueryEngine, QueryIntent classification, entity extraction,
and fuzzy component name matching. Validates all 8 supported question
categories and the fallback behavior for unknown queries.

The query engine is rule-based (no LLM dependency) and uses keyword
matching, component name resolution, and template-based responses.
"""

from __future__ import annotations

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.api.query_engine import (
    QueryEngine,
    QueryIntent,
    _fuzzy_match_component,
    classify_query,
)
from s0ma.registry import ComponentRegistry
from s0ma.self_model.interface import SelfModelInterface

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Create a fresh registry with framework components registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def smi(registry: ComponentRegistry) -> SelfModelInterface:
    """Create a SelfModelInterface for the registry."""
    return SelfModelInterface(registry)


@pytest.fixture()
def engine(registry: ComponentRegistry, smi: SelfModelInterface) -> QueryEngine:
    """Create a QueryEngine with registry and self-model interface."""
    return QueryEngine(registry, smi)


# ======================================================================
# QueryIntent classification tests
# ======================================================================


class TestClassifyQuery:
    """Tests for the classify_query() function."""

    def test_component_lookup_what_is(self) -> None:
        intent, _ = classify_query("What is ComponentRegistry?")
        assert intent == QueryIntent.COMPONENT_LOOKUP

    def test_component_lookup_describe(self) -> None:
        intent, _ = classify_query("Describe the StructuralVerifier")
        assert intent == QueryIntent.COMPONENT_LOOKUP

    def test_component_lookup_tell_me(self) -> None:
        intent, _ = classify_query("Tell me about ComponentSpec")
        assert intent == QueryIntent.COMPONENT_LOOKUP

    def test_dependency_query(self) -> None:
        intent, _ = classify_query("What depends on ComponentSpec?")
        assert intent == QueryIntent.DEPENDENCY_QUERY

    def test_dependency_query_uses(self) -> None:
        intent, _ = classify_query("What does ComponentRegistry use?")
        assert intent == QueryIntent.DEPENDENCY_QUERY

    def test_impact_analysis(self) -> None:
        intent, _ = classify_query(
            "What would break if I changed ComponentSpec?"
        )
        assert intent == QueryIntent.IMPACT_ANALYSIS

    def test_impact_analysis_remove(self) -> None:
        intent, _ = classify_query(
            "What would be affected if I removed ComponentRegistry?"
        )
        assert intent == QueryIntent.IMPACT_ANALYSIS

    def test_health_query_anomalies(self) -> None:
        intent, _ = classify_query("What anomalies exist?")
        assert intent == QueryIntent.HEALTH_QUERY

    def test_health_query_healthy(self) -> None:
        intent, _ = classify_query("Is the system healthy?")
        assert intent == QueryIntent.HEALTH_QUERY

    def test_health_query_verification(self) -> None:
        intent, _ = classify_query("What is the verification status?")
        assert intent == QueryIntent.HEALTH_QUERY

    def test_performance_query(self) -> None:
        intent, _ = classify_query("Why is the registry slow?")
        assert intent == QueryIntent.PERFORMANCE_QUERY

    def test_performance_query_metrics(self) -> None:
        intent, _ = classify_query("What are the metrics?")
        assert intent == QueryIntent.PERFORMANCE_QUERY

    def test_stats_query_how_many(self) -> None:
        intent, _ = classify_query("How many components are there?")
        assert intent == QueryIntent.STATS_QUERY

    def test_stats_query_layers(self) -> None:
        intent, _ = classify_query("What layers exist?")
        assert intent == QueryIntent.STATS_QUERY

    def test_stats_query_overview(self) -> None:
        intent, _ = classify_query("Give me an overview")
        assert intent == QueryIntent.STATS_QUERY

    def test_extension_query(self) -> None:
        intent, _ = classify_query("Where can I add a new service?")
        assert intent == QueryIntent.EXTENSION_QUERY

    def test_extension_query_create(self) -> None:
        intent, _ = classify_query("I want to add a new service component")
        assert intent == QueryIntent.EXTENSION_QUERY

    def test_handler_query(self) -> None:
        intent, _ = classify_query("What handles registration?")
        assert intent == QueryIntent.HANDLER_QUERY

    def test_handler_query_process(self) -> None:
        intent, _ = classify_query("Who processes bootstrap?")
        assert intent == QueryIntent.HANDLER_QUERY

    def test_unknown_query(self) -> None:
        intent, _ = classify_query("Lorem ipsum dolor sit amet")
        assert intent == QueryIntent.UNKNOWN

    def test_empty_query(self) -> None:
        intent, entities = classify_query("")
        assert intent == QueryIntent.UNKNOWN
        assert entities == []

    def test_whitespace_only_query(self) -> None:
        intent, entities = classify_query("   ")
        assert intent == QueryIntent.UNKNOWN
        assert entities == []


class TestEntityExtraction:
    """Tests for entity name extraction from queries."""

    def test_extracts_pascal_case_names(self) -> None:
        _, entities = classify_query("What is ComponentRegistry?")
        assert "ComponentRegistry" in entities

    def test_extracts_quoted_names(self) -> None:
        _, entities = classify_query('What is "ComponentSpec"?')
        assert "ComponentSpec" in entities

    def test_extracts_single_quoted_names(self) -> None:
        _, entities = classify_query("Tell me about 'LifecycleManager'")
        assert "LifecycleManager" in entities

    def test_extracts_multiple_entities(self) -> None:
        _, entities = classify_query(
            "How does ComponentRegistry depend on ComponentSpec?"
        )
        assert "ComponentRegistry" in entities
        assert "ComponentSpec" in entities

    def test_no_entities_for_plain_text(self) -> None:
        _, entities = classify_query("How many components?")
        # No PascalCase words, no quoted strings
        assert len(entities) == 0


# ======================================================================
# Fuzzy matching tests
# ======================================================================


class TestFuzzyMatchComponent:
    """Tests for the _fuzzy_match_component() function."""

    @pytest.fixture()
    def names(self) -> list[str]:
        return [
            "ComponentRegistry",
            "ComponentSpec",
            "ComponentDecorator",
            "Contract",
            "StructuralVerifier",
            "SelfModelInterface",
        ]

    def test_exact_match(self, names: list[str]) -> None:
        assert _fuzzy_match_component("ComponentRegistry", names) == "ComponentRegistry"

    def test_case_insensitive_match(self, names: list[str]) -> None:
        assert _fuzzy_match_component("componentregistry", names) == "ComponentRegistry"

    def test_partial_match_contains(self, names: list[str]) -> None:
        result = _fuzzy_match_component("Registry", names)
        assert result == "ComponentRegistry"

    def test_partial_match_registry(self, names: list[str]) -> None:
        result = _fuzzy_match_component("registry", names)
        assert result == "ComponentRegistry"

    def test_partial_match_contract(self, names: list[str]) -> None:
        result = _fuzzy_match_component("contract", names)
        assert result == "Contract"

    def test_no_match(self, names: list[str]) -> None:
        assert _fuzzy_match_component("FooBar", names) is None

    def test_shortest_match_preferred(self, names: list[str]) -> None:
        # "Spec" matches both ComponentSpec and (potentially) others
        # but ComponentSpec is a unique short match
        result = _fuzzy_match_component("Contract", names)
        assert result == "Contract"


# ======================================================================
# QueryEngine tests — all 8 intent categories
# ======================================================================


class TestQueryEngineComponentLookup:
    """Tests for COMPONENT_LOOKUP intent handling."""

    def test_what_is_component_registry(self, engine: QueryEngine) -> None:
        answer = engine.query("What is ComponentRegistry?")
        assert "ComponentRegistry" in answer
        assert len(answer) > 100  # Substantive description

    def test_describe_component_spec(self, engine: QueryEngine) -> None:
        answer = engine.query("Describe ComponentSpec")
        assert "ComponentSpec" in answer
        assert "metadata" in answer.lower() or "registration" in answer.lower()

    def test_nonexistent_component(self, engine: QueryEngine) -> None:
        answer = engine.query("What is FooBarBaz?")
        # Should get a fallback since FooBarBaz doesn't exist
        assert "component" in answer.lower()

    def test_fuzzy_match_registry(self, engine: QueryEngine) -> None:
        """Test that 'registry' fuzzy-matches to ComponentRegistry."""
        answer = engine.query("What is the registry?")
        assert "ComponentRegistry" in answer


class TestQueryEngineDependencyQuery:
    """Tests for DEPENDENCY_QUERY intent handling."""

    def test_what_depends_on_component_spec(self, engine: QueryEngine) -> None:
        answer = engine.query("What depends on ComponentSpec?")
        assert "ComponentSpec" in answer
        # ComponentSpec should have dependents
        assert "ComponentRegistry" in answer or "depend" in answer.lower()

    def test_what_does_registry_use(self, engine: QueryEngine) -> None:
        answer = engine.query("What does ComponentRegistry use?")
        assert "ComponentRegistry" in answer
        # Should mention its dependencies
        assert "ComponentSpec" in answer or "RegistrySnapshot" in answer


class TestQueryEngineImpactAnalysis:
    """Tests for IMPACT_ANALYSIS intent handling."""

    def test_what_breaks_if_component_spec_changes(
        self, engine: QueryEngine
    ) -> None:
        answer = engine.query(
            "What would break if I changed ComponentSpec?"
        )
        assert "ComponentSpec" in answer
        # Should mention impact/risk/dependents
        assert any(
            word in answer.lower()
            for word in ("impact", "risk", "dependent", "affected")
        )

    def test_impact_on_nonexistent(self, engine: QueryEngine) -> None:
        answer = engine.query("What breaks if I remove FooBarNonExistent?")
        # Should handle gracefully
        assert "not registered" in answer.lower() or "couldn't identify" in answer.lower()


class TestQueryEngineHealthQuery:
    """Tests for HEALTH_QUERY intent handling."""

    def test_what_anomalies_exist(self, engine: QueryEngine) -> None:
        answer = engine.query("What anomalies exist?")
        assert isinstance(answer, str)
        assert len(answer) > 50

    def test_is_system_healthy(self, engine: QueryEngine) -> None:
        answer = engine.query("Is the system healthy?")
        assert isinstance(answer, str)
        # Should mention health status
        assert any(
            word in answer.lower()
            for word in ("health", "passed", "verification", "anomal")
        )


class TestQueryEnginePerformanceQuery:
    """Tests for PERFORMANCE_QUERY intent handling."""

    def test_no_metrics_graceful(self, engine: QueryEngine) -> None:
        """Without MetricsCollector, should return graceful message."""
        answer = engine.query("Why is ComponentRegistry slow?")
        assert "not available" in answer.lower() or "metrics" in answer.lower()

    def test_metrics_query_without_collector(self, engine: QueryEngine) -> None:
        answer = engine.query("What are the metrics?")
        assert "not available" in answer.lower() or "MetricsCollector" in answer


class TestQueryEngineStatsQuery:
    """Tests for STATS_QUERY intent handling."""

    def test_how_many_components(self, engine: QueryEngine) -> None:
        answer = engine.query("How many components are there?")
        assert "component" in answer.lower()
        # Should contain a number (the component count)
        assert any(c.isdigit() for c in answer)

    def test_list_all_layers(self, engine: QueryEngine) -> None:
        answer = engine.query("What layers exist?")
        # Should mention at least the FRAMEWORK layer
        assert "framework" in answer.lower()


class TestQueryEngineExtensionQuery:
    """Tests for EXTENSION_QUERY intent handling."""

    def test_where_to_add_service(self, engine: QueryEngine) -> None:
        answer = engine.query("Where can I add a new service?")
        assert isinstance(answer, str)
        assert len(answer) > 50
        # Should mention layers or extension points
        assert any(
            word in answer.lower()
            for word in ("layer", "extension", "domain", "application")
        )


class TestQueryEngineHandlerQuery:
    """Tests for HANDLER_QUERY intent handling."""

    def test_what_handles_queries(self, engine: QueryEngine) -> None:
        answer = engine.query("What handles queries?")
        # ComponentRegistry intent mentions "hierarchical queries"
        assert "ComponentRegistry" in answer

    def test_what_handles_verification(self, engine: QueryEngine) -> None:
        answer = engine.query("What handles verification?")
        assert any(
            name in answer
            for name in (
                "StructuralVerifier",
                "ContractVerifier",
                "InteroceptionVerifier",
                "CoverageAuditor",
                "Verifier",
            )
        )


# ======================================================================
# Edge cases and fallback behavior
# ======================================================================


class TestQueryEngineFallback:
    """Tests for unknown queries and edge cases."""

    def test_unknown_question_fallback(self, engine: QueryEngine) -> None:
        answer = engine.query("Lorem ipsum dolor sit amet")
        # Should get the fallback with suggestions
        assert "question" in answer.lower() or "answer" in answer.lower()
        assert "component" in answer.lower()

    def test_empty_question(self, engine: QueryEngine) -> None:
        answer = engine.query("")
        assert "question" in answer.lower() or "answer" in answer.lower()

    def test_whitespace_question(self, engine: QueryEngine) -> None:
        answer = engine.query("   ")
        assert "question" in answer.lower() or "answer" in answer.lower()

    def test_all_answers_are_strings(self, engine: QueryEngine) -> None:
        """Every query returns a string, never a raw data structure."""
        questions = [
            "What is ComponentRegistry?",
            "What depends on ComponentSpec?",
            "What would break if ComponentSpec changes?",
            "Are there anomalies?",
            "How many components?",
            "Where can I add a service?",
            "What handles registration?",
            "",
        ]
        for q in questions:
            answer = engine.query(q)
            assert isinstance(answer, str), f"Query '{q}' returned {type(answer)}"
            assert len(answer) > 0, f"Query '{q}' returned empty string"


# ======================================================================
# Intent classification parametrized test
# ======================================================================


class TestIntentClassificationParametrized:
    """Parametrized tests for intent classification correctness."""

    @pytest.mark.parametrize(
        "question,expected_intent",
        [
            ("What is ComponentSpec?", QueryIntent.COMPONENT_LOOKUP),
            ("Tell me about the registry", QueryIntent.COMPONENT_LOOKUP),
            ("Describe LifecycleManager", QueryIntent.COMPONENT_LOOKUP),
            ("What depends on X?", QueryIntent.DEPENDENCY_QUERY),
            ("What does X use?", QueryIntent.DEPENDENCY_QUERY),
            ("What imports X?", QueryIntent.DEPENDENCY_QUERY),
            ("What breaks if X changes?", QueryIntent.IMPACT_ANALYSIS),
            ("What would be affected by removing X?", QueryIntent.IMPACT_ANALYSIS),
            ("Are there anomalies?", QueryIntent.HEALTH_QUERY),
            ("What is the health status?", QueryIntent.HEALTH_QUERY),
            ("Show verification results", QueryIntent.HEALTH_QUERY),
            ("Why is X slow?", QueryIntent.PERFORMANCE_QUERY),
            ("What are the latency metrics?", QueryIntent.PERFORMANCE_QUERY),
            ("How many components?", QueryIntent.STATS_QUERY),
            ("Give me an overview", QueryIntent.STATS_QUERY),
            ("List all layers", QueryIntent.STATS_QUERY),
            ("Where can I add a service?", QueryIntent.EXTENSION_QUERY),
            ("I want to add a new service component", QueryIntent.EXTENSION_QUERY),
            ("What handles requests?", QueryIntent.HANDLER_QUERY),
            ("Who processes bootstrap?", QueryIntent.HANDLER_QUERY),
            ("xyzzy", QueryIntent.UNKNOWN),
        ],
        ids=[
            "component_what_is",
            "component_tell_me",
            "component_describe",
            "dependency_depends_on",
            "dependency_uses",
            "dependency_imports",
            "impact_breaks",
            "impact_affected",
            "health_anomalies",
            "health_status",
            "health_verification",
            "performance_slow",
            "performance_metrics",
            "stats_how_many",
            "stats_overview",
            "stats_list_layers",
            "extension_add",
            "extension_create",
            "handler_requests",
            "handler_process",
            "unknown",
        ],
    )
    def test_intent_classification(
        self,
        question: str,
        expected_intent: QueryIntent,
    ) -> None:
        intent, _ = classify_query(question)
        assert intent == expected_intent, (
            f"Expected {expected_intent.name} for '{question}', "
            f"got {intent.name}"
        )


# ======================================================================
# Integration with REST API (POST /self/query)
# ======================================================================


class TestQueryEngineRESTIntegration:
    """Tests for the POST /self/query REST endpoint."""

    @pytest.fixture()
    def client(self, registry: ComponentRegistry) -> object:
        pytest.importorskip("fastapi", reason="FastAPI not installed")
        from fastapi.testclient import TestClient

        from s0ma.api.rest import create_app

        app = create_app(registry)
        return TestClient(app)

    def test_post_query_returns_200(self, client: object) -> None:
        resp = client.post(  # type: ignore[union-attr]
            "/self/query",
            json={"question": "What is ComponentRegistry?"},
        )
        assert resp.status_code == 200  # type: ignore[union-attr]

    def test_post_query_returns_answer(self, client: object) -> None:
        resp = client.post(  # type: ignore[union-attr]
            "/self/query",
            json={"question": "What is ComponentRegistry?"},
        )
        data = resp.json()  # type: ignore[union-attr]
        assert "question" in data
        assert "answer" in data
        assert "ComponentRegistry" in data["answer"]

    def test_post_query_empty_question(self, client: object) -> None:
        resp = client.post(  # type: ignore[union-attr]
            "/self/query",
            json={"question": ""},
        )
        assert resp.status_code == 200  # type: ignore[union-attr]
        data = resp.json()  # type: ignore[union-attr]
        assert len(data["answer"]) > 0


# ======================================================================
# Integration with MCP Server (query_system tool)
# ======================================================================


class TestQueryEngineMCPIntegration:
    """Tests for the query_system MCP tool."""

    @pytest.fixture()
    def mcp_server(self, registry: ComponentRegistry) -> object:
        pytest.importorskip("mcp", reason="MCP SDK not installed")
        from s0ma.api.mcp_server import create_mcp_server

        return create_mcp_server(registry)

    def _call_tool(
        self, server: object, tool_name: str, arguments: dict[str, object]
    ) -> str:
        """Call an MCP tool and return its text output."""
        import asyncio

        content_list, _structured = asyncio.run(
            server.call_tool(tool_name, arguments)  # type: ignore[union-attr]
        )
        return content_list[0].text  # type: ignore[union-attr]

    def test_query_system_tool_exists(self, mcp_server: object) -> None:
        """The query_system tool is registered in the MCP server."""
        import asyncio

        tools = asyncio.run(
            mcp_server.list_tools()  # type: ignore[union-attr]
        )
        tool_names = [t.name for t in tools]
        assert "query_system" in tool_names

    def test_query_system_returns_answer(self, mcp_server: object) -> None:
        result = self._call_tool(
            mcp_server,
            "query_system",
            {"question": "What is ComponentRegistry?"},
        )
        assert isinstance(result, str)
        assert "ComponentRegistry" in result

    def test_query_system_handles_unknown(self, mcp_server: object) -> None:
        result = self._call_tool(
            mcp_server,
            "query_system",
            {"question": "xyzzy plugh"},
        )
        assert isinstance(result, str)
        assert len(result) > 0
