"""An operation name resolves to the component that provides it.

Every describe surface accepts a component name. An agent mostly knows a
system through the operations it calls (the tool names), so a name that
is not a component but is an entry of some component's ``provides:``
list resolves to that component, and the answer says so. These tests
pin that on the registry, the self-model interface, the analyzers, the
query engine and the MCP server; the runtime adapter's version lives in
``test_runtime_self_context.py``.
"""

from __future__ import annotations

import pytest

from s0ma.api.query_engine import QueryEngine
from s0ma.exceptions import RegistryIntegrityError
from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.self_model.analyzers import (
    compute_impact_analysis,
    explain_dependency_chain,
)
from s0ma.types import ComponentKind, Layer


def _service(
    name: str,
    provides: list[str],
    *,
    module_path: str = "",
    dependencies: list[str] | None = None,
) -> ComponentSpec:
    return ComponentSpec(
        name=name,
        kind=ComponentKind.SERVICE,
        layer=Layer.INFRASTRUCTURE,
        intent=f"{name} serves the agent through its named operations.",
        dependencies=list(dependencies or []),
        metadata={"provides": provides},
        module_path=module_path,
    )


@pytest.fixture
def registry() -> ComponentRegistry:
    reg = ComponentRegistry(persist=False)
    reg.register(_service("ShellExecutor", ["run_shell"], module_path="fr3d_build.shell"))
    reg.register(
        _service(
            "CodeExecutor",
            ["get_spec", "pip_install", "run_code"],
            module_path="fr3d_build.executor",
            dependencies=["ShellExecutor"],
        )
    )
    reg.register(
        _service(
            "WebBrowser",
            ["get_spec", "fetch_url", "web_search"],
            module_path="fr3d_build.browser",
        )
    )
    return reg


class TestRegistryResolution:
    def test_find_providers_matches_exactly(self, registry: ComponentRegistry) -> None:
        assert [s.name for s in registry.find_providers("fetch_url")] == ["WebBrowser"]
        assert sorted(s.name for s in registry.find_providers("get_spec")) == [
            "CodeExecutor", "WebBrowser",
        ]
        assert registry.find_providers("Fetch_URL") == []
        assert registry.find_providers("ShellExecutor") == []

    def test_a_component_name_resolves_without_an_operation(
        self, registry: ComponentRegistry
    ) -> None:
        resolution = registry.resolve_component("WebBrowser")
        assert resolution.spec is not None and resolution.spec.name == "WebBrowser"
        assert resolution.operation is None
        assert resolution.note is None

    def test_an_operation_name_resolves_to_its_one_provider(
        self, registry: ComponentRegistry
    ) -> None:
        resolution = registry.resolve_component("fetch_url")
        assert resolution.spec is not None and resolution.spec.name == "WebBrowser"
        assert resolution.operation == "fetch_url"
        assert resolution.note == "fetch_url is an operation of browser::WebBrowser"

    def test_a_shared_operation_lists_every_provider(
        self, registry: ComponentRegistry
    ) -> None:
        resolution = registry.resolve_component("get_spec")
        assert resolution.spec is None
        assert resolution.candidates == (
            "executor::CodeExecutor", "browser::WebBrowser",
        )

    def test_an_unknown_name_resolves_to_nothing(
        self, registry: ComponentRegistry
    ) -> None:
        resolution = registry.resolve_component("teleport")
        assert resolution.spec is None
        assert resolution.candidates == ()

    def test_a_component_name_wins_over_an_operation_of_the_same_name(
        self, registry: ComponentRegistry
    ) -> None:
        registry.register(_service("fetch_url", ["fetch"], module_path="fr3d_build.legacy"))
        resolution = registry.resolve_component("fetch_url")
        assert resolution.spec is not None and resolution.spec.name == "fetch_url"
        assert resolution.operation is None

    def test_display_name_is_module_qualified_when_known(self) -> None:
        assert _service("X", [], module_path="fr3d_build.browser").display_name == "browser::X"
        assert _service("X", []).display_name == "X"


class TestSelfModelInterface:
    def test_describe_component_by_operation_says_so(
        self, registry: ComponentRegistry
    ) -> None:
        text = SelfModelInterface(registry).describe_component("fetch_url")
        assert text.startswith(
            "fetch_url is an operation of browser::WebBrowser; this describes that component."
        )
        assert "## WebBrowser" in text
        assert "  - fetch_url" in text

    def test_dependents_are_the_providers(self, registry: ComponentRegistry) -> None:
        text = SelfModelInterface(registry).describe_component("run_shell")
        assert "run_shell is an operation of shell::ShellExecutor" in text
        assert "CodeExecutor (service)" in text

    def test_shared_operation_raises_naming_the_providers(
        self, registry: ComponentRegistry
    ) -> None:
        with pytest.raises(RegistryIntegrityError) as excinfo:
            SelfModelInterface(registry).describe_component("get_spec")
        message = str(excinfo.value)
        assert "'get_spec' is an operation of 2 components" in message
        assert "executor::CodeExecutor" in message and "browser::WebBrowser" in message

    def test_unknown_name_keeps_the_registered_listing(
        self, registry: ComponentRegistry
    ) -> None:
        with pytest.raises(RegistryIntegrityError, match="not registered"):
            SelfModelInterface(registry).describe_component("teleport")

    def test_impact_analysis_by_operation(self, registry: ComponentRegistry) -> None:
        text = SelfModelInterface(registry).get_impact_analysis("run_shell")
        assert "## Impact Analysis: ShellExecutor" in text
        assert "run_shell is an operation of ShellExecutor" in text
        assert "CodeExecutor" in text


class TestAnalyzers:
    def test_impact_report_records_the_operation(
        self, registry: ComponentRegistry
    ) -> None:
        report = compute_impact_analysis(registry, "run_shell")
        assert report.component_name == "ShellExecutor"
        assert report.direct_dependents == ["CodeExecutor"]
        assert report.details["operation"] == "run_shell"
        assert "operation" not in compute_impact_analysis(registry, "ShellExecutor").details

    def test_impact_of_a_shared_operation_raises(
        self, registry: ComponentRegistry
    ) -> None:
        with pytest.raises(RegistryIntegrityError, match="is an operation of 2 components"):
            compute_impact_analysis(registry, "get_spec")

    def test_dependency_chain_accepts_operations_on_both_sides(
        self, registry: ComponentRegistry
    ) -> None:
        text = explain_dependency_chain(registry, "pip_install", "run_shell")
        assert text.startswith(
            "pip_install is an operation of executor::CodeExecutor.\n"
            "run_shell is an operation of shell::ShellExecutor.\n"
        )
        assert "CodeExecutor" in text and "ShellExecutor" in text
        assert "No dependency relationship" not in text

    def test_dependency_chain_plain_names_are_unchanged(
        self, registry: ComponentRegistry
    ) -> None:
        text = explain_dependency_chain(registry, "CodeExecutor", "ShellExecutor")
        assert "is an operation of" not in text


class TestQueryEngine:
    def test_question_about_an_operation_answers_for_its_provider(
        self, registry: ComponentRegistry
    ) -> None:
        engine = QueryEngine(registry, SelfModelInterface(registry))
        answer = engine.query("What breaks if run_shell is removed?")
        assert answer.startswith("run_shell is an operation of shell::ShellExecutor.")
        assert "## Impact Analysis: ShellExecutor" in answer
        assert "CodeExecutor" in answer

    def test_shared_operation_is_named_rather_than_guessed(
        self, registry: ComponentRegistry
    ) -> None:
        engine = QueryEngine(registry, SelfModelInterface(registry))
        answer = engine.query("What is get_spec?")
        assert "'get_spec' is an operation of 2 components" in answer
        assert "CodeExecutor" in answer and "WebBrowser" in answer


class TestMcpServer:
    def test_find_component_by_operation(self, registry: ComponentRegistry) -> None:
        pytest.importorskip("mcp", reason="MCP SDK not installed")
        import asyncio

        from s0ma.api.mcp_server import create_mcp_server

        server = create_mcp_server(registry)

        def call(tool: str, **arguments: str) -> str:
            content, _ = asyncio.run(server.call_tool(tool, arguments))
            return str(content[0].text)

        found = call("find_component", name="fetch_url")
        assert found.startswith("fetch_url is an operation of browser::WebBrowser")
        impact = call("get_impact", component="run_shell")
        assert "## Impact Analysis: ShellExecutor" in impact
        chain = call("explain_dependency", source="pip_install", target="run_shell")
        assert "pip_install is an operation of executor::CodeExecutor." in chain
