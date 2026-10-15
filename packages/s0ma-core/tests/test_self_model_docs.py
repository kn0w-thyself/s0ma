"""Tests for the M5 documentation surface on :class:`SelfModelInterface`.

Covers:
    * ``describe_docs()`` — registry-wide doc/example overview, including
      the empty-registry path.
    * ``describe_doc(name)`` — doc-ref vs. doc-guide dispatch and the
      informational "not found" path (does not raise).
    * ``get_docs_for_component(name)`` and
      ``get_examples_for_component(name)`` — reverse-index surfacing.
    * ``get_drift_status()`` — v1 hash-presence report, including the
      no-docs and some-missing-hashes paths.
    * ``get_impact_analysis(component)`` — now lists affected docs and
      affected examples when the component is covered by them.
"""

from __future__ import annotations

import pytest

from s0ma.models import (
    AssertExpr,
    ComponentSpec,
    EntityRef,
    FilterExpr,
    Section,
    SourceSpan,
)
from s0ma.registry import ComponentRegistry
from s0ma.self_model import SelfModelInterface
from s0ma.types import ComponentKind, Layer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Return a fresh in-memory registry for each test."""
    return ComponentRegistry(persist=False)


@pytest.fixture()
def smi(registry: ComponentRegistry) -> SelfModelInterface:
    """SelfModelInterface wired to the fresh registry."""
    return SelfModelInterface(registry)


def _span() -> SourceSpan:
    return SourceSpan(file="src/sample.s0ma", start_line=1, end_line=20)


def _register_chat_router(registry: ComponentRegistry) -> None:
    """Register a ``ChatRouter`` component plus docs/examples covering it."""
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


# ---------------------------------------------------------------------------
# describe_docs()
# ---------------------------------------------------------------------------


class TestDescribeDocs:
    def test_returns_informative_message_when_empty(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_docs()
        assert isinstance(result, str)
        assert "No documentation artifacts registered" in result

    def test_lists_doc_refs_and_guides_and_examples(
        self,
        registry: ComponentRegistry,
        smi: SelfModelInterface,
    ) -> None:
        _register_chat_router(registry)
        result = smi.describe_docs()
        assert "# Documentation Overview" in result
        assert "1 doc-ref(s), 1 doc-guide(s), 1 example(s)" in result
        assert "all-services" in result
        assert "chat-routing-guide" in result
        assert "hello-chat" in result


# ---------------------------------------------------------------------------
# describe_doc(name)
# ---------------------------------------------------------------------------


class TestDescribeDoc:
    def test_returns_doc_ref_detail(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.describe_doc("all-services")
        assert "doc-ref: all-services" in result
        assert "Intent: List every service in the nerve module" in result
        # Filter expression raw text should appear.
        assert "ChatRouter" in result
        assert "Content hash: hash-1" in result

    def test_returns_doc_guide_detail(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.describe_doc("chat-routing-guide")
        assert "doc-guide: chat-routing-guide" in result
        assert "ChatRouter dispatches messages." in result
        # Referenced example surfaced.
        assert "hello-chat" in result

    def test_not_found_when_registry_has_no_docs(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.describe_doc("nope")
        assert "No documentation named 'nope'" in result
        # Clarifies subsystem is in place when nothing has registered.
        assert "no doc-ref or doc-guide has been registered" in result

    def test_not_found_lists_registered_docs_when_present(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.describe_doc("nope")
        assert "No documentation named 'nope'" in result
        assert "all-services" in result
        assert "chat-routing-guide" in result

    def test_does_not_raise_for_unknown(self, smi: SelfModelInterface) -> None:
        # Informational contract: no exception, just text.
        smi.describe_doc("definitely-missing")


# ---------------------------------------------------------------------------
# get_docs_for_component / get_examples_for_component
# ---------------------------------------------------------------------------


class TestReverseIndexSurfaces:
    def test_docs_for_component_surfaces_matches(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_docs_for_component("ChatRouter")
        assert "Documentation covering 'ChatRouter'" in result
        assert "1 doc-ref(s), 1 doc-guide(s)" in result
        assert "all-services" in result
        assert "chat-routing-guide" in result

    def test_docs_for_component_handles_no_matches(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_docs_for_component("SomethingElse")
        assert "No documentation artifacts cover 'SomethingElse'" in result

    def test_examples_for_component_surfaces_matches(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_examples_for_component("ChatRouter")
        assert "Examples demonstrating 'ChatRouter'" in result
        assert "hello-chat" in result
        assert "runs_in=standalone" in result

    def test_examples_for_component_handles_no_matches(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_examples_for_component("SomethingElse")
        assert "No canonical examples demonstrate 'SomethingElse'" in result

    def test_string_shortcut_is_accepted(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        # ``module::name`` shortcut routed through M4 reverse index.
        result = smi.get_examples_for_component("nerve::ChatRouter")
        assert "hello-chat" in result


# ---------------------------------------------------------------------------
# get_drift_status()
# ---------------------------------------------------------------------------


class TestDriftStatus:
    def test_empty_registry_reports_nothing_to_check(
        self, smi: SelfModelInterface
    ) -> None:
        result = smi.get_drift_status()
        assert "no documentation registered" in result

    def test_populated_registry_reports_hash_presence(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_drift_status()
        assert "Documentation Drift Status" in result
        assert "doc-refs: 1/1" in result
        assert "doc-guides: 1/1" in result
        # Stored hashes ("hash-1", "hash-2") are placeholders, so the
        # M7 drift check must flag both as drifted against the
        # freshly-recomputed transitive hash.
        assert "Drift check:" in result
        assert "2/2" in result
        assert "drifted" in result
        assert "all-services" in result
        assert "chat-routing-guide" in result

    def test_missing_hashes_are_listed(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        # Register one doc-ref with no hash to exercise the "missing"
        # branch of format_drift_status.
        registry.register_doc_ref(
            name="unhashed-doc",
            module="nerve",
            intent="Doc-ref without a computed content hash",
            format="markdown",
            output="docs/unhashed.md",
            covers=[],
            sections=[],
            content_hash="",
            source_span=_span(),
        )
        result = smi.get_drift_status()
        assert "doc-refs: 0/1" in result
        assert "Registrations missing a content hash" in result
        assert "doc-ref: unhashed-doc" in result


# ---------------------------------------------------------------------------
# get_impact_analysis extensions
# ---------------------------------------------------------------------------


class TestImpactAnalysisDocsExtension:
    def test_impact_analysis_lists_affected_docs_and_examples(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        _register_chat_router(registry)
        result = smi.get_impact_analysis("ChatRouter")
        assert "Impact Analysis: ChatRouter" in result
        assert "Affected documentation" in result
        assert "all-services" in result
        assert "chat-routing-guide" in result
        assert "Affected examples" in result
        assert "hello-chat" in result

    def test_impact_analysis_omits_doc_sections_when_no_matches(
        self, registry: ComponentRegistry, smi: SelfModelInterface
    ) -> None:
        registry.register(
            ComponentSpec(
                name="Loner",
                kind=ComponentKind.SERVICE,
                layer=Layer.DOMAIN,
                intent="A component with no docs or examples",
            )
        )
        result = smi.get_impact_analysis("Loner")
        assert "Affected documentation" not in result
        assert "Affected examples" not in result
