"""Tests for the S0ma REST API (Phase 3B, Milestone 9).

Tests the FastAPI REST endpoints that wrap the SelfModelInterface
for HTTP access by external tools.

Uses FastAPI's TestClient (backed by httpx) for testing without
running a server.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi.testclient import TestClient

from s0ma._bootstrap import bootstrap_register
from s0ma.api.rest import create_app
from s0ma.registry import ComponentRegistry


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Create a fresh registry with framework components registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def client(registry: ComponentRegistry) -> TestClient:
    """Create a FastAPI test client with the self-model API."""
    app = create_app(registry)
    return TestClient(app)


class TestGetOverview:
    """Tests for GET /self/overview."""

    def test_returns_200_with_system_overview(self, client: TestClient) -> None:
        resp = client.get("/self/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "component_count" in data
        assert "framework_component_count" in data
        assert "layers" in data

    def test_text_contains_natural_language(self, client: TestClient) -> None:
        resp = client.get("/self/overview")
        data = resp.json()
        text = data["text"]
        # Should contain natural language, not raw data structures
        assert "S0ma" in text
        assert "component" in text.lower()

    def test_component_count_matches_registry(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        resp = client.get("/self/overview")
        data = resp.json()
        assert data["component_count"] == registry.count()

    def test_layers_are_populated(self, client: TestClient) -> None:
        resp = client.get("/self/overview")
        data = resp.json()
        layers = data["layers"]
        assert isinstance(layers, dict)
        assert len(layers) > 0
        # Framework layer should have components
        assert "FRAMEWORK" in layers
        assert len(layers["FRAMEWORK"]) > 0


class TestGetComponents:
    """Tests for GET /self/components."""

    def test_returns_200_with_component_list(self, client: TestClient) -> None:
        resp = client.get("/self/components")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "components" in data
        assert "total" in data

    def test_total_matches_component_count(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        resp = client.get("/self/components")
        data = resp.json()
        assert data["total"] == registry.count()
        assert len(data["components"]) == registry.count()

    def test_components_contain_expected_fields(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/components")
        data = resp.json()
        # Check the first component has expected fields
        comp = data["components"][0]
        assert "name" in comp
        assert "kind" in comp
        assert "layer" in comp
        assert "intent" in comp

    def test_text_is_summary(self, client: TestClient) -> None:
        resp = client.get("/self/components")
        data = resp.json()
        assert "Registered components" in data["text"]


class TestGetComponent:
    """Tests for GET /self/component/{name}."""

    def test_returns_200_for_existing_component(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/component/ComponentRegistry")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "spec" in data

    def test_text_contains_component_details(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/component/ComponentRegistry")
        data = resp.json()
        text = data["text"]
        assert "ComponentRegistry" in text
        assert "framework" in text.lower()

    def test_spec_has_correct_name(self, client: TestClient) -> None:
        resp = client.get("/self/component/ComponentRegistry")
        data = resp.json()
        assert data["spec"]["name"] == "ComponentRegistry"

    def test_returns_404_for_nonexistent_component(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/component/NonExistentComponent")
        assert resp.status_code == 404
        data = resp.json()
        assert "not registered" in data["detail"]


class TestGetHealth:
    """Tests for GET /self/health."""

    def test_returns_200_with_health_status(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "passed" in data
        assert "anomaly_count" in data

    def test_text_contains_health_info(self, client: TestClient) -> None:
        resp = client.get("/self/health")
        data = resp.json()
        text = data["text"]
        # Should contain health-related language
        assert "health" in text.lower() or "healthy" in text.lower()


class TestGetAnomalies:
    """Tests for GET /self/anomalies."""

    def test_returns_200_with_anomalies(self, client: TestClient) -> None:
        resp = client.get("/self/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "anomalies" in data
        assert "total" in data
        assert isinstance(data["anomalies"], list)

    def test_text_is_natural_language(self, client: TestClient) -> None:
        resp = client.get("/self/anomalies")
        data = resp.json()
        text = data["text"]
        # Should be natural language, not raw data
        assert isinstance(text, str)
        assert len(text) > 0


class TestGetGraph:
    """Tests for GET /self/graph."""

    def test_returns_200_with_graph(self, client: TestClient) -> None:
        resp = client.get("/self/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "json_graph" in data
        assert "dot_format" in data

    def test_json_graph_is_adjacency_list(self, client: TestClient) -> None:
        resp = client.get("/self/graph")
        data = resp.json()
        graph = data["json_graph"]
        assert isinstance(graph, dict)
        # Components with dependencies should appear
        assert len(graph) > 0
        # Values should be lists of strings
        for deps in graph.values():
            assert isinstance(deps, list)

    def test_dot_format_is_valid_dot(self, client: TestClient) -> None:
        resp = client.get("/self/graph")
        data = resp.json()
        dot = data["dot_format"]
        assert dot.startswith("digraph s0ma {")
        assert dot.endswith("}")
        assert "->" in dot  # Should have edges

    def test_text_describes_dependencies(self, client: TestClient) -> None:
        resp = client.get("/self/graph")
        data = resp.json()
        text = data["text"]
        # Should mention dependency relationships
        assert "depend" in text.lower() or "->" in text


class TestGetImpact:
    """Tests for GET /self/impact/{name}."""

    def test_returns_200_for_existing_component(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/impact/ComponentRegistry")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "component_name" in data
        assert "risk_level" in data
        assert "direct_dependents" in data
        assert "transitive_dependents" in data
        assert "total_affected" in data

    def test_component_registry_has_high_impact(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/impact/ComponentRegistry")
        data = resp.json()
        assert data["component_name"] == "ComponentRegistry"
        # ComponentRegistry should have dependents
        assert data["total_affected"] > 0

    def test_returns_404_for_nonexistent_component(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/impact/NonExistentComponent")
        assert resp.status_code == 404

    def test_text_contains_impact_analysis(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/impact/ComponentRegistry")
        data = resp.json()
        text = data["text"]
        assert "impact" in text.lower() or "dependents" in text.lower()


class TestGetExtensions:
    """Tests for GET /self/extensions."""

    def test_returns_200_with_extension_points(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/extensions")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "extension_points" in data
        assert "total" in data

    def test_extension_points_have_structure(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/extensions")
        data = resp.json()
        assert data["total"] > 0
        point = data["extension_points"][0]
        assert "layer" in point
        assert "suggested_kinds" in point
        assert "potential_dependencies" in point
        assert "rationale" in point

    def test_text_is_actionable(self, client: TestClient) -> None:
        resp = client.get("/self/extensions")
        data = resp.json()
        text = data["text"]
        # Should be substantial and actionable
        assert len(text) > 100


class TestResponseConsistency:
    """Cross-cutting tests for response consistency."""

    def test_all_endpoints_return_text_field(
        self, client: TestClient
    ) -> None:
        """Every endpoint returns a 'text' field with natural language."""
        endpoints = [
            "/self/overview",
            "/self/components",
            "/self/component/ComponentRegistry",
            "/self/health",
            "/self/anomalies",
            "/self/graph",
            "/self/impact/ComponentRegistry",
            "/self/extensions",
        ]
        for endpoint in endpoints:
            resp = client.get(endpoint)
            assert resp.status_code == 200, (
                f"{endpoint} returned {resp.status_code}"
            )
            data = resp.json()
            assert "text" in data, (
                f"{endpoint} missing 'text' field"
            )
            text = data["text"]
            assert isinstance(text, str), (
                f"{endpoint} 'text' is not a string"
            )
            assert len(text) > 0, (
                f"{endpoint} 'text' is empty"
            )

    def test_all_endpoints_return_valid_json(
        self, client: TestClient
    ) -> None:
        """All endpoints return valid JSON."""
        endpoints = [
            "/self/overview",
            "/self/components",
            "/self/health",
            "/self/anomalies",
            "/self/graph",
            "/self/extensions",
        ]
        for endpoint in endpoints:
            resp = client.get(endpoint)
            assert resp.status_code == 200
            # json() would raise if invalid
            data = resp.json()
            assert isinstance(data, dict)


class TestCreateApp:
    """Tests for the create_app factory function."""

    def test_create_app_returns_fastapi_instance(
        self, registry: ComponentRegistry
    ) -> None:
        from fastapi import FastAPI

        app = create_app(registry)
        assert isinstance(app, FastAPI)

    def test_create_app_without_optional_params(
        self, registry: ComponentRegistry
    ) -> None:
        """create_app works with only the required registry argument."""
        app = create_app(registry)
        client = TestClient(app)
        resp = client.get("/self/overview")
        assert resp.status_code == 200

    def test_create_app_with_metrics_collector(
        self, registry: ComponentRegistry
    ) -> None:
        """create_app accepts an optional metrics_collector."""
        from s0ma.verifiers.interoception import MetricsCollector

        collector = MetricsCollector()
        app = create_app(registry, metrics_collector=collector)
        client = TestClient(app)
        resp = client.get("/self/overview")
        assert resp.status_code == 200

    def test_app_version_tracks_package_version(
        self, registry: ComponentRegistry
    ) -> None:
        """The served OpenAPI version is the lockstep package version.

        Asserting against ``__version__`` (not a literal) guards the
        coupling itself, so the test never needs a release bump and a
        hardcoded string can never silently rot into /openapi.json again.
        """
        from s0ma import __version__

        app = create_app(registry)
        assert app.version == __version__
        assert app.openapi()["info"]["version"] == __version__


class TestDotGraphFormatter:
    """Tests for the DOT graph formatter (added in Milestone 9)."""

    def test_empty_graph_produces_valid_dot(self) -> None:
        from s0ma.self_model.formatters import format_dependency_graph_dot

        result = format_dependency_graph_dot({})
        assert result.startswith("digraph s0ma {")
        assert result.endswith("}")

    def test_simple_graph_produces_edges(self) -> None:
        from s0ma.self_model.formatters import format_dependency_graph_dot

        graph = {"A": ["B", "C"], "B": ["C"], "C": []}
        result = format_dependency_graph_dot(graph)
        assert '"A" -> "B"' in result
        assert '"A" -> "C"' in result
        assert '"B" -> "C"' in result

    def test_graph_with_components_includes_layer_colors(self) -> None:
        from s0ma.models import ComponentSpec
        from s0ma.self_model.formatters import format_dependency_graph_dot
        from s0ma.types import ComponentKind, Layer

        spec_a = ComponentSpec(
            name="A",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Test component A for DOT formatter",
        )
        spec_b = ComponentSpec(
            name="B",
            kind=ComponentKind.ADAPTER,
            layer=Layer.INFRASTRUCTURE,
            intent="Test component B for DOT formatter",
        )

        graph = {"A": ["B"], "B": []}
        components = {"A": spec_a, "B": spec_b}
        result = format_dependency_graph_dot(graph, components)

        # Should have layer-specific colors
        assert "fillcolor" in result
        assert '"A" -> "B"' in result
        # Should include kind in label
        assert "service" in result
        assert "adapter" in result

    def test_graph_with_no_edges_still_valid(self) -> None:
        from s0ma.self_model.formatters import format_dependency_graph_dot

        graph = {"A": [], "B": [], "C": []}
        result = format_dependency_graph_dot(graph)
        assert result.startswith("digraph s0ma {")
        assert result.endswith("}")
        # Should list nodes but no edges
        assert '"A"' in result
        assert '"B"' in result
        assert '"C"' in result
