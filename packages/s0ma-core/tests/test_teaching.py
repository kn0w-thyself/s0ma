"""Tests for the s0ma teaching capability (Phase 3B).

Tests the TeachingProvider class, MCP teaching tools/resources,
and the TEACHING_QUERY intent in the QueryEngine.

Verifies that documentation is served from actual source files (no
duplication) and that live registry examples are accurate.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from s0ma._bootstrap import bootstrap_register
from s0ma.api.teaching import (
    _TOPIC_TO_HEADING,
    TeachingProvider,
    resolve_docs_dir,
)
from s0ma.registry import ComponentRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Create a fresh registry with framework components registered."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def teacher(registry: ComponentRegistry) -> TeachingProvider:
    """Create a TeachingProvider with auto-resolved docs directory."""
    return TeachingProvider(registry)


#: A path no installation has. Passing it as ``slice_path`` is how a test
#: asks for a provider with no teaching slice: an explicit path that cannot
#: be read leaves the provider with none, deliberately and with no fallback
#: behind it (see ``TeachingProvider._slice_source``).
NO_SUCH_FILE = Path("/nonexistent_dir/slice.json")


@pytest.fixture()
def teacher_no_docs(registry: ComponentRegistry) -> TeachingProvider:
    """A TeachingProvider with neither a teaching slice nor a checkout guide.

    The last rung of the degradation ladder, and since F8 a state no
    released installation reaches — the slice ships inside the wheel. It is
    constructed here on purpose so the message at the bottom of the ladder
    stays tested rather than becoming unreachable *and* unchecked.
    """
    return TeachingProvider(
        registry, docs_dir=Path("/nonexistent_dir"), slice_path=NO_SUCH_FILE
    )


@pytest.fixture()
def teacher_guide_only(registry: ComponentRegistry) -> TeachingProvider:
    """A TeachingProvider with no slice, reading the checkout's user guide.

    The pre-F8 behaviour, still reachable in a tree where the slice has
    never been composed. Every test using this fixture is a test of the
    *fallback* path.
    """
    return TeachingProvider(registry, slice_path=NO_SUCH_FILE)


# ---------------------------------------------------------------------------
# TeachingProvider — docs resolution
# ---------------------------------------------------------------------------


class TestDocsResolution:
    """Tests for documentation directory resolution."""

    def test_resolve_docs_dir_finds_docs(self) -> None:
        """resolve_docs_dir() locates docs/ in the development layout."""
        docs_dir = resolve_docs_dir()
        # In the development layout, docs should be found
        assert docs_dir is not None
        assert (docs_dir / "s0ma_user_guide.md").is_file()

    def test_docs_available_true_when_docs_exist(self, teacher: TeachingProvider) -> None:
        """docs_available is True when documentation files are on disk."""
        assert teacher.docs_available is True

    def test_docs_available_false_when_no_docs(
        self, teacher_no_docs: TeachingProvider
    ) -> None:
        """docs_available is False when docs directory doesn't exist."""
        assert teacher_no_docs.docs_available is False


# ---------------------------------------------------------------------------
# TeachingProvider — documentation serving
# ---------------------------------------------------------------------------


class TestDocumentationServing:
    """Tests for serving documentation from disk."""

    def test_get_user_guide_returns_content(self, teacher: TeachingProvider) -> None:
        """get_user_guide() returns the full user guide from disk."""
        result = teacher.get_user_guide()
        assert "s0ma User Guide" in result
        assert "Registration IS creation" in result

    def test_get_user_guide_contains_all_sections(
        self, teacher: TeachingProvider
    ) -> None:
        """User guide contains all major sections."""
        result = teacher.get_user_guide()
        assert "Section 1: Project Setup" in result
        assert "Section 2: Creating Components" in result
        assert "Appendix C: Compliance Rules" in result

    def test_get_compliance_rules_extracts_appendix_c(
        self, teacher: TeachingProvider
    ) -> None:
        """get_compliance_rules() returns only Appendix C."""
        result = teacher.get_compliance_rules()
        assert "Appendix C: Compliance Rules" in result
        assert "F-1" in result  # Foundational rule
        assert "C.11" in result  # Checklist section

    def test_get_compliance_rules_does_not_include_other_sections(
        self, teacher: TeachingProvider
    ) -> None:
        """Compliance rules extraction doesn't include unrelated sections."""
        result = teacher.get_compliance_rules()
        # Should NOT start with Section 1 content
        assert "## What s0ma Is" not in result
        assert "## Section 1:" not in result

    def test_get_architecture_returns_content(
        self, teacher: TeachingProvider
    ) -> None:
        """get_architecture() returns architecture.md from disk."""
        result = teacher.get_architecture()
        assert isinstance(result, str)
        assert len(result) > 100  # Non-trivial content

    def test_get_section_extracts_by_heading(
        self, teacher: TeachingProvider
    ) -> None:
        """get_section() extracts a specific section by heading."""
        result = teacher.get_section("Section 2: Creating Components")
        assert "@component" in result
        assert "ComponentKind" in result

    def test_get_section_not_found(self, teacher: TeachingProvider) -> None:
        """get_section() returns message for unknown heading."""
        result = teacher.get_section("Nonexistent Section XYZ")
        assert "not found" in result.lower()

    def test_get_compliance_checklist_returns_checklist(
        self, teacher: TeachingProvider
    ) -> None:
        """get_compliance_checklist() returns the C.11 checklist."""
        result = teacher.get_compliance_checklist()
        assert "checklist" in result.lower() or "[ ]" in result
        assert "s0ma.initialize()" in result or "s0ma.verify()" in result

    def test_docs_unavailable_returns_helpful_message(
        self, teacher_no_docs: TeachingProvider
    ) -> None:
        """With neither slice nor guide, returns a clear fallback message."""
        result = teacher_no_docs.get_user_guide()
        assert "not available" in result.lower()
        assert "describe_system" in result  # Points to alternative tools

    def test_compliance_rules_unavailable_returns_helpful_message(
        self, teacher_no_docs: TeachingProvider
    ) -> None:
        """Compliance rules also degrade gracefully when nothing is readable."""
        result = teacher_no_docs.get_compliance_rules()
        assert "not available" in result.lower()

    def test_user_guide_falls_back_to_the_slice_map(
        self, registry: ComponentRegistry
    ) -> None:
        """No checkout guide, but a packaged slice: the reader gets the map.

        The wheel condition, reproduced in process. Before F8 this returned
        "documentation files are not available in this installation"; the
        slice ships inside the package, so it returns what is here.
        """
        teacher = TeachingProvider(registry, docs_dir=Path("/nonexistent_dir"))
        result = teacher.get_user_guide()
        assert "not available" not in result.lower()
        assert "concept:nerve" in result
        assert "teaching snapshot" in result

    def test_compliance_rules_name_what_is_here_instead(
        self, registry: ComponentRegistry
    ) -> None:
        """Without the guide, the compliance answer routes rather than stops."""
        teacher = TeachingProvider(registry, docs_dir=Path("/nonexistent_dir"))
        result = teacher.get_compliance_rules()
        assert "concept:strictness-mode" in result
        assert "teaching snapshot" in result


# ---------------------------------------------------------------------------
# TeachingProvider — live registry examples
# ---------------------------------------------------------------------------


class TestLiveRegistryExamples:
    """Tests for live component template generation."""

    def test_get_component_template_returns_template(
        self, teacher: TeachingProvider
    ) -> None:
        """get_component_template() returns a valid @component template."""
        result = teacher.get_component_template()
        assert "@component(" in result
        assert "ComponentKind." in result
        assert "Layer." in result
        assert "intent=" in result

    def test_get_component_template_is_python_code(
        self, teacher: TeachingProvider
    ) -> None:
        """Template is wrapped in a python code block."""
        result = teacher.get_component_template()
        assert "```python" in result
        assert "```" in result

    def test_get_component_template_uses_real_data(
        self, teacher: TeachingProvider
    ) -> None:
        """Template uses an actual component from the registry."""
        result = teacher.get_component_template()
        # Should contain a real component name from the registry
        all_names = list(teacher._registry.get_all().keys())
        found = any(name in result for name in all_names)
        assert found, "Template should contain a real registered component name"

    def test_get_component_template_filters_by_kind(
        self, teacher: TeachingProvider
    ) -> None:
        """Kind parameter filters the selected component."""
        result = teacher.get_component_template(kind="FRAMEWORK")
        assert "ComponentKind.FRAMEWORK" in result

    def test_get_component_template_invalid_kind(
        self, teacher: TeachingProvider
    ) -> None:
        """Invalid kind returns a helpful error message."""
        result = teacher.get_component_template(kind="INVALID_KIND")
        assert "Unknown ComponentKind" in result
        assert "SERVICE" in result  # Lists valid kinds


# ---------------------------------------------------------------------------
# TeachingProvider — topic-based learning
# ---------------------------------------------------------------------------


class TestTopicLearning:
    """Tests for the learn_topic() method, over the packaged teaching slice.

    Every assertion here is about the *current* answer to a question core
    has always been asked. The pins that a question still answers **at
    all** live in ``test_teaching_slice.py``, over the whole legacy
    vocabulary at once; these are the handful worth reading in place.
    """

    def test_learn_creating_components(self, teacher: TeachingProvider) -> None:
        """'creating components' teaches the file, and shows a real one."""
        result = teacher.learn_topic("creating components")
        assert "concept:s0ma-file" in result
        assert "@component" in result  # the live template is still appended
        assert "A real one, from this system" in result

    def test_learn_compliance_rules(self, teacher: TeachingProvider) -> None:
        """'compliance' teaches how severely the build treats its findings."""
        result = teacher.learn_topic("compliance")
        assert "concept:strictness-mode" in result
        assert "strictness" in result.lower()

    def test_learn_rules_keyword(self, teacher: TeachingProvider) -> None:
        """'rules' reaches the same topic 'compliance' does."""
        assert teacher.learn_topic("rules") == teacher.learn_topic("compliance")

    def test_learn_modifying(self, teacher: TeachingProvider) -> None:
        """'modifying' teaches the loop a change is made inside."""
        result = teacher.learn_topic("modifying")
        assert "concept:check-and-build-loop" in result

    def test_learn_removing(self, teacher: TeachingProvider) -> None:
        """'removing' teaches the gate that refuses a stale record."""
        result = teacher.learn_topic("removing")
        assert "concept:drift-gate" in result

    def test_learn_troubleshooting(self, teacher: TeachingProvider) -> None:
        """'troubleshooting' teaches why the build refuses."""
        result = teacher.learn_topic("troubleshooting")
        assert "concept:drift-gate" in result

    def test_learn_setup(self, teacher: TeachingProvider) -> None:
        """'setup' names the function you actually call."""
        result = teacher.learn_topic("setup")
        assert "python:s0ma.initialize" in result
        assert "initialize" in result.lower()

    def test_learn_a_concept_by_its_name(self, teacher: TeachingProvider) -> None:
        """A term is a question: 'nerve' returns the nerve entry, whole."""
        result = teacher.learn_topic("nerve")
        assert result.startswith("# nerve")
        assert "concept:nerve" in result
        assert "What it is" in result

    def test_learn_a_concept_by_an_old_name(self, teacher: TeachingProvider) -> None:
        """A name somebody arrives holding resolves to the one that replaced it."""
        assert teacher.learn_topic("observable function") == teacher.learn_topic("nerve")

    def test_learn_unknown_topic_returns_topic_list(
        self, teacher: TeachingProvider
    ) -> None:
        """A question nothing answers returns everything that is here."""
        result = teacher.learn_topic("banana pancake recipe")
        assert "What s0ma can teach you here" in result
        assert "concept:nerve" in result
        assert "index:concepts" in result

    def test_every_answer_says_where_it_came_from(
        self, teacher: TeachingProvider
    ) -> None:
        """Release and snapshot on every answer (architecture §9.7)."""
        current = teacher.teaching_slice()
        assert current is not None
        for topic in ("nerve", "compliance", "banana pancake recipe"):
            answer = teacher.learn_topic(topic)
            assert current.release_version in answer
            assert current.snapshot_hash in answer

    def test_learn_with_nothing_readable_degrades(
        self, teacher_no_docs: TeachingProvider
    ) -> None:
        """With neither slice nor guide, topic learning still says something."""
        result = teacher_no_docs.learn_topic("compliance")
        assert "not available" in result.lower()

    def test_learn_falls_back_to_the_guide_without_a_slice(
        self, teacher_guide_only: TeachingProvider
    ) -> None:
        """No slice, but a checkout: the pre-F8 path still answers.

        The fallback is a fallback and not dead code — a tree where the
        documentation application has never run still teaches from the
        guide beside it.
        """
        assert teacher_guide_only.teaching_slice() is None
        result = teacher_guide_only.learn_topic("compliance")
        assert "Compliance Rules" in result

    @pytest.mark.parametrize(
        "heading", sorted({heading for _, heading in _TOPIC_TO_HEADING})
    )
    def test_every_fallback_heading_exists_in_the_guide(self, heading: str) -> None:
        """Each address in the fallback table names a real guide heading.

        The table is a list of addresses inside one Markdown file, and
        nothing had ever checked that the addresses resolve. One did not:
        ``"Section 8: Troubleshooting"`` named a heading no version of the
        guide has carried — troubleshooting is section 9, section 8 is
        testing — so five keywords answered a "section not found" string
        instead of the section they were written for. It was invisible
        because the guide is the fallback path, exercised only in a
        checkout with no composed slice.

        Renumber a section in the guide and this test says so, which is
        the whole reason it exists: the G2 merge made that file's heading
        set load-bearing for a reader who has no slice.
        """
        docs_dir = resolve_docs_dir()
        assert docs_dir is not None, "the development checkout should have the guide"
        guide = (docs_dir / "s0ma_user_guide.md").read_text(encoding="utf-8")
        headings = {
            line.lstrip("#").strip()
            for line in guide.splitlines()
            if line.startswith("#")
        }
        assert heading in headings, (
            f"the fallback table addresses {heading!r}, which is not a heading "
            f"in s0ma_user_guide.md. Either restore the heading or repoint the "
            f"entry in _TOPIC_TO_HEADING."
        )

    def test_the_fallback_answers_troubleshooting_with_the_section(
        self, teacher_guide_only: TeachingProvider
    ) -> None:
        """The repaired entry returns the section, not the not-found string."""
        result = teacher_guide_only.learn_topic("troubleshooting")
        assert result.startswith("## Section 9: Troubleshooting")
        assert "not found" not in result


# ---------------------------------------------------------------------------
# MCP Integration — resources and tools
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously for testing."""
    return asyncio.run(coro)


def _call_tool(
    server: Any, tool_name: str, arguments: dict[str, Any] | None = None
) -> str:
    """Call an MCP tool and return its text output."""
    args = arguments or {}
    content_list, _structured = _run(server.call_tool(tool_name, args))
    return content_list[0].text


try:
    import mcp  # noqa: F401

    _has_mcp = True
except ImportError:
    _has_mcp = False


@pytest.mark.skipif(not _has_mcp, reason="MCP SDK not installed")
class TestTeachingMCPTools:
    """Tests for MCP teaching tools."""

    @pytest.fixture()
    def mcp_server(self, registry: ComponentRegistry) -> Any:
        from s0ma.api.mcp_server import create_mcp_server

        return create_mcp_server(registry)

    def test_learn_about_s0ma_tool_exists(self, mcp_server: Any) -> None:
        """learn_about_s0ma tool is registered."""
        tools = _run(mcp_server.list_tools())
        tool_names = {t.name for t in tools}
        assert "learn_about_s0ma" in tool_names

    def test_learn_about_s0ma_returns_content(self, mcp_server: Any) -> None:
        """learn_about_s0ma returns current teaching content with identity."""
        result = _call_tool(
            mcp_server, "learn_about_s0ma", {"topic": "compliance"}
        )
        assert "concept:strictness-mode" in result
        assert "teaching snapshot" in result

    def test_learn_about_s0ma_creating(self, mcp_server: Any) -> None:
        """learn_about_s0ma('creating components') returns decorator info."""
        result = _call_tool(
            mcp_server, "learn_about_s0ma", {"topic": "creating components"}
        )
        assert "@component" in result

    def test_get_component_example_tool_exists(self, mcp_server: Any) -> None:
        """get_component_example tool is registered."""
        tools = _run(mcp_server.list_tools())
        tool_names = {t.name for t in tools}
        assert "get_component_example" in tool_names

    def test_get_component_example_returns_template(self, mcp_server: Any) -> None:
        """get_component_example returns a component template."""
        result = _call_tool(mcp_server, "get_component_example")
        assert "@component(" in result
        assert "ComponentKind." in result

    def test_get_compliance_checklist_tool_exists(self, mcp_server: Any) -> None:
        """get_compliance_checklist tool is registered."""
        tools = _run(mcp_server.list_tools())
        tool_names = {t.name for t in tools}
        assert "get_compliance_checklist" in tool_names

    def test_get_compliance_checklist_returns_checklist(
        self, mcp_server: Any
    ) -> None:
        """get_compliance_checklist returns the checklist content."""
        result = _call_tool(mcp_server, "get_compliance_checklist")
        assert "checklist" in result.lower() or "[ ]" in result

    def test_teaching_tools_have_descriptions(self, mcp_server: Any) -> None:
        """All teaching tools have non-empty descriptions."""
        tools = _run(mcp_server.list_tools())
        teaching_names = {
            "learn_about_s0ma", "get_component_example",
            "get_compliance_checklist",
        }
        for tool in tools:
            if tool.name in teaching_names:
                assert tool.description is not None
                assert len(tool.description) > 10


# ---------------------------------------------------------------------------
# QueryEngine — TEACHING_QUERY intent
# ---------------------------------------------------------------------------


class TestTeachingQueryIntegration:
    """Tests for TEACHING_QUERY intent in the QueryEngine."""

    def test_how_do_i_classified_as_teaching(self) -> None:
        """'How do I create a component?' is classified as TEACHING_QUERY."""
        from s0ma.api.query_engine import QueryIntent, classify_query

        intent, _ = classify_query("How do I create a component?")
        assert intent == QueryIntent.TEACHING_QUERY

    def test_rules_classified_as_teaching(self) -> None:
        """'What are the rules?' is classified as TEACHING_QUERY."""
        from s0ma.api.query_engine import QueryIntent, classify_query

        intent, _ = classify_query("What are the compliance rules?")
        assert intent == QueryIntent.TEACHING_QUERY

    def test_how_to_classified_as_teaching(self) -> None:
        """'How to register a component?' is classified as TEACHING_QUERY."""
        from s0ma.api.query_engine import QueryIntent, classify_query

        intent, _ = classify_query("How to register a component with s0ma?")
        assert intent == QueryIntent.TEACHING_QUERY

    def test_show_me_how_classified_as_teaching(self) -> None:
        """'Show me how to...' is classified as TEACHING_QUERY."""
        from s0ma.api.query_engine import QueryIntent, classify_query

        intent, _ = classify_query("Show me how to register a component")
        assert intent == QueryIntent.TEACHING_QUERY

    def test_teach_me_classified_as_teaching(self) -> None:
        """'Teach me about...' is classified as TEACHING_QUERY."""
        from s0ma.api.query_engine import QueryIntent, classify_query

        intent, _ = classify_query("Teach me about s0ma")
        assert intent == QueryIntent.TEACHING_QUERY

    def test_teaching_query_handler_returns_docs(
        self, registry: ComponentRegistry
    ) -> None:
        """TEACHING_QUERY handler returns documentation content."""
        from s0ma.api.query_engine import QueryEngine
        from s0ma.self_model.interface import SelfModelInterface

        smi = SelfModelInterface(registry)
        qe = QueryEngine(registry, smi)
        result = qe.query("How do I create a component?")
        # Should return Section 2 content about creating components
        assert "@component" in result or "creating" in result.lower()
        assert isinstance(result, str)
        assert len(result) > 50


# ---------------------------------------------------------------------------
# Bootstrap — TeachingProvider registration
# ---------------------------------------------------------------------------


class TestTeachingBootstrap:
    """Tests that TeachingProvider is properly registered in bootstrap."""

    def test_teaching_provider_registered(
        self, registry: ComponentRegistry
    ) -> None:
        """TeachingProvider is registered as a framework component."""
        spec = registry.get("TeachingProvider")
        assert spec is not None
        assert spec.is_framework is True

    def test_teaching_provider_has_correct_metadata(
        self, registry: ComponentRegistry
    ) -> None:
        """TeachingProvider has correct kind, layer, and intent."""
        from s0ma.types import ComponentKind, Layer

        spec = registry.get("TeachingProvider")
        assert spec is not None
        assert spec.kind == ComponentKind.FRAMEWORK
        assert spec.layer == Layer.FRAMEWORK
        assert len(spec.intent) >= 10
        assert "teaching" in spec.intent.lower() or "documentation" in spec.intent.lower()

    def test_teaching_provider_declares_dependencies(
        self, registry: ComponentRegistry
    ) -> None:
        """TeachingProvider declares its ComponentRegistry dependency."""
        spec = registry.get("TeachingProvider")
        assert spec is not None
        assert "ComponentRegistry" in spec.dependencies
