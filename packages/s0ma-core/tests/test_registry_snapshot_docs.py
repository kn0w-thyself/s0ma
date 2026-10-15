"""Tests for documentation extensions on RegistrySnapshot (M4).

Covers:
    * Snapshot construction includes ``doc_refs`` / ``doc_guides`` /
      ``examples`` populated from the registry stores.
    * ``to_dict`` / ``to_json`` emit the new keys only when non-empty so
      existing snapshot consumers see no schema churn until the
      documentation subsystem is in use.
    * ``describe()`` renders Documentation / Examples sections when
      doc registrations are present and omits them otherwise.
    * Reverse-index methods ``examples_for`` and ``docs_for`` resolve
      :class:`EntityRef` and ``"module::name"`` string shortcuts and
      return correctly-shaped results.
"""

from __future__ import annotations

import json

import pytest

from s0ma.models import (
    AssertExpr,
    DocGuideRegistration,
    DocRefRegistration,
    DocsForResult,
    EntityRef,
    ExampleRegistration,
    FilterExpr,
    RegistrySnapshot,
    Section,
    SourceSpan,
)
from s0ma.registry import ComponentRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def registry() -> ComponentRegistry:
    """Return a fresh in-memory registry for each test."""
    return ComponentRegistry(persist=False)


def _span() -> SourceSpan:
    return SourceSpan(file="src/sample.s0ma", start_line=1, end_line=20)


def _populate(registry: ComponentRegistry) -> None:
    """Register one of each doc-subsystem type covering ChatRouter."""
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
        asserts=[
            AssertExpr(expression="True", source_span=_span()),
        ],
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
# Snapshot construction
# ---------------------------------------------------------------------------

class TestSnapshotPopulation:

    def test_empty_registry_has_empty_doc_stores(
        self,
        registry: ComponentRegistry,
    ) -> None:
        snap = registry.snapshot()
        assert snap.doc_refs == {}
        assert snap.doc_guides == {}
        assert snap.examples == {}

    def test_populated_registry_surfaces_docs(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        assert "all-services" in snap.doc_refs
        assert isinstance(
            snap.doc_refs["all-services"], DocRefRegistration
        )
        assert "chat-routing-guide" in snap.doc_guides
        assert isinstance(
            snap.doc_guides["chat-routing-guide"], DocGuideRegistration
        )
        assert "hello-chat" in snap.examples
        assert isinstance(snap.examples["hello-chat"], ExampleRegistration)

    def test_snapshot_is_a_copy_not_a_reference(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        # Mutating the snapshot's dicts must not corrupt the registry.
        snap.doc_refs.clear()
        assert registry.get_doc_ref("all-services") is not None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSnapshotSerialization:

    def test_to_dict_omits_doc_keys_when_empty(
        self,
        registry: ComponentRegistry,
    ) -> None:
        d = registry.snapshot().to_dict()
        assert "doc_refs" not in d
        assert "doc_guides" not in d
        assert "examples" not in d

    def test_to_dict_emits_doc_keys_when_present(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        d = registry.snapshot().to_dict()
        assert "all-services" in d["doc_refs"]
        assert "chat-routing-guide" in d["doc_guides"]
        assert "hello-chat" in d["examples"]

    def test_to_json_round_trip(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        parsed = json.loads(snap.to_json())
        assert parsed["doc_refs"]["all-services"]["format"] == "markdown"
        assert (
            parsed["examples"]["hello-chat"]["demonstrates"][0]["name"]
            == "ChatRouter"
        )

    def test_to_dict_field_order_stable_for_legacy_consumers(
        self,
        registry: ComponentRegistry,
    ) -> None:
        # No doc registrations → existing keys appear in the same order
        # they did before M4 and no new keys precede ``snapshot_at``.
        keys = list(registry.snapshot().to_dict().keys())
        assert keys == [
            "components",
            "component_count",
            "framework_component_count",
            "layers",
            "dependency_graph",
            "modules",
            "edges",
            "test_registrations",
            "ir",
            "plugins",
            "snapshot_at",
        ]


# ---------------------------------------------------------------------------
# describe()
# ---------------------------------------------------------------------------

class TestSnapshotDescribe:

    def test_describe_omits_doc_sections_when_empty(
        self,
        registry: ComponentRegistry,
    ) -> None:
        desc = registry.snapshot().describe()
        assert "DOCUMENTATION" not in desc
        assert "EXAMPLES" not in desc

    def test_describe_includes_doc_sections_when_populated(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        desc = registry.snapshot().describe()
        assert "DOCUMENTATION" in desc
        assert "doc-ref all-services" in desc
        assert "doc-guide chat-routing-guide" in desc
        assert "EXAMPLES" in desc
        assert "hello-chat" in desc
        assert "Demonstrates: nerve:ChatRouter" in desc


# ---------------------------------------------------------------------------
# Reverse indices
# ---------------------------------------------------------------------------

class TestExamplesFor:

    def test_returns_examples_for_entity_ref(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        results = snap.examples_for(
            EntityRef(kind="nerve", name="ChatRouter", module="nerve")
        )
        assert [ex.name for ex in results] == ["hello-chat"]

    def test_returns_examples_for_string_shortcut(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        assert [
            ex.name for ex in snap.examples_for("nerve::ChatRouter")
        ] == ["hello-chat"]
        assert [
            ex.name for ex in snap.examples_for("ChatRouter")
        ] == ["hello-chat"]

    def test_returns_empty_for_unknown_entity(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        assert snap.examples_for("DoesNotExist") == []

    def test_module_disambiguation(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        # Same name under a different module should not match.
        snap = registry.snapshot()
        assert snap.examples_for("other::ChatRouter") == []


class TestDocsFor:

    def test_returns_guides_for_entity_ref(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        result = snap.docs_for(
            EntityRef(kind="nerve", name="ChatRouter", module="nerve")
        )
        assert isinstance(result, DocsForResult)
        assert [g.name for g in result.guides] == ["chat-routing-guide"]

    def test_returns_refs_when_filter_text_matches(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        result = snap.docs_for("ChatRouter")
        # Coarse v1 textual containment: filter's raw mentions ChatRouter.
        assert [r.name for r in result.refs] == ["all-services"]
        assert [g.name for g in result.guides] == ["chat-routing-guide"]

    def test_returns_empty_result_for_unknown_entity(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        result = snap.docs_for("DoesNotExist")
        assert result.is_empty()
        assert result.refs == []
        assert result.guides == []

    def test_docs_for_result_to_dict(
        self,
        registry: ComponentRegistry,
    ) -> None:
        _populate(registry)
        snap = registry.snapshot()
        payload = snap.docs_for("ChatRouter").to_dict()
        # Both lists present and JSON-serializable.
        json.dumps(payload)
        assert payload["refs"][0]["name"] == "all-services"
        assert payload["guides"][0]["name"] == "chat-routing-guide"


# ---------------------------------------------------------------------------
# Constructor compatibility (no registry)
# ---------------------------------------------------------------------------

class TestRegistrySnapshotDirectConstruction:

    def test_default_constructor_omits_new_dicts_cleanly(self) -> None:
        snap = RegistrySnapshot(
            components={},
            component_count=0,
            framework_component_count=0,
            layers={},
            dependency_graph={},
        )
        assert snap.doc_refs == {}
        assert snap.doc_guides == {}
        assert snap.examples == {}
        assert snap.examples_for("anything") == []
        assert snap.docs_for("anything").is_empty()
