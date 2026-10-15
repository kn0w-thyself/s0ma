"""Tests for the M8 documentation-subsystem REST endpoints.

Covers the five new endpoints added in Milestone 8:

* ``GET /self/docs``          — registry-wide doc + example overview.
* ``GET /self/doc/{name}``    — doc-ref / doc-guide detail, 404 on miss.
* ``GET /self/examples``      — list all registered examples.
* ``GET /self/example/{name}``— single example detail, 404 on miss.
* ``GET /self/drift``         — drift-status report (via M7 content hashes).

Uses FastAPI's ``TestClient`` (backed by httpx) for request-level testing
without starting a real server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("fastapi", reason="FastAPI not installed")

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

from s0ma._bootstrap import bootstrap_register
from s0ma.api.rest import create_app
from s0ma.hashing import content_hash
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


def _span() -> SourceSpan:
    return SourceSpan(file="src/sample.s0ma", start_line=1, end_line=20)


def _register_chat_router(
    registry: ComponentRegistry, *, with_real_hashes: bool = False
) -> None:
    """Register a ``ChatRouter`` component plus covering docs / example.

    When ``with_real_hashes`` is True, registers the doc-ref and doc-guide
    with content hashes recomputed from the snapshot so the drift check
    reports a clean state. Otherwise uses placeholder hashes that will
    read as drifted.
    """
    registry.register(
        ComponentSpec(
            name="ChatRouter",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Routes chat messages to the correct handler",
        )
    )
    chat_router = EntityRef(kind="nerve", name="ChatRouter", module="nerve")

    ref_hash = "hash-1"
    guide_hash = "hash-2"
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
        content_hash=ref_hash,
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
        content_hash=guide_hash,
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

    if with_real_hashes:
        # Recompute with both registrations already present so the
        # transitive hash over the snapshot is stable.
        snap = registry.snapshot()
        real_ref_hash = content_hash(
            snap.doc_refs["all-services"], snap, transpiler_version="unknown"
        )
        real_guide_hash = content_hash(
            snap.doc_guides["chat-routing-guide"],
            snap,
            transpiler_version="unknown",
        )
        # Re-register with the computed hashes (idempotent=True for upsert).
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
            content_hash=real_ref_hash,
            source_span=_span(),
            idempotent=True,
        )
        registry.register_doc_guide(
            name="chat-routing-guide",
            module="nerve",
            intent="Explain ChatRouter behavior",
            format="markdown",
            output="docs/chat-routing.md",
            covers=[chat_router],
            asserts=[AssertExpr(expression="True", source_span=_span())],
            examples=[
                EntityRef(kind="example", name="hello-chat", module="nerve")
            ],
            body="ChatRouter dispatches messages.",
            content_hash=real_guide_hash,
            source_span=_span(),
            idempotent=True,
        )


@pytest.fixture()
def registry() -> ComponentRegistry:
    """Bootstrapped registry — mirrors existing REST-test conventions."""
    reg = ComponentRegistry(persist=False)
    bootstrap_register(reg)
    return reg


@pytest.fixture()
def client(registry: ComponentRegistry) -> Iterator[TestClient]:
    app = create_app(registry)
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# GET /self/docs
# ---------------------------------------------------------------------------


class TestGetDocs:
    def test_empty_registry_returns_200_with_zero_counts(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_doc_refs"] == 0
        assert data["total_doc_guides"] == 0
        assert data["total_examples"] == 0
        assert data["doc_refs"] == []
        assert data["doc_guides"] == []
        assert data["examples"] == []
        assert "No documentation artifacts registered" in data["text"]

    def test_populated_registry_lists_all_artifacts(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/docs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_doc_refs"] == 1
        assert data["total_doc_guides"] == 1
        assert data["total_examples"] == 1
        assert data["doc_refs"][0]["name"] == "all-services"
        assert data["doc_guides"][0]["name"] == "chat-routing-guide"
        assert data["examples"][0]["name"] == "hello-chat"
        # Natural-language text should mention all three names
        assert "all-services" in data["text"]
        assert "chat-routing-guide" in data["text"]
        assert "hello-chat" in data["text"]

    def test_response_has_text_and_data_fields(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        data = client.get("/self/docs").json()
        assert isinstance(data["text"], str) and len(data["text"]) > 0
        for key in ("doc_refs", "doc_guides", "examples"):
            assert isinstance(data[key], list)


# ---------------------------------------------------------------------------
# GET /self/doc/{name}
# ---------------------------------------------------------------------------


class TestGetDoc:
    def test_returns_doc_ref_detail(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/doc/all-services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "doc-ref"
        assert data["spec"]["name"] == "all-services"
        assert data["spec"]["format"] == "markdown"
        assert "doc-ref: all-services" in data["text"]

    def test_returns_doc_guide_detail(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/doc/chat-routing-guide")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "doc-guide"
        assert data["spec"]["name"] == "chat-routing-guide"
        assert "doc-guide: chat-routing-guide" in data["text"]

    def test_returns_404_for_unknown_doc(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/doc/not-registered")
        assert resp.status_code == 404
        assert "not registered" in resp.json()["detail"]

    def test_returns_404_when_registry_has_no_docs(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/doc/anything")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /self/examples
# ---------------------------------------------------------------------------


class TestGetExamples:
    def test_empty_registry_returns_200_with_empty_list(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/examples")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["examples"] == []
        assert "No examples registered" in data["text"]

    def test_populated_registry_lists_examples(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/examples")
        data = resp.json()
        assert data["total"] == 1
        assert data["examples"][0]["name"] == "hello-chat"
        assert data["examples"][0]["runs_in"] == "standalone"
        assert "hello-chat" in data["text"]
        assert "runs_in=standalone" in data["text"]


# ---------------------------------------------------------------------------
# GET /self/example/{name}
# ---------------------------------------------------------------------------


class TestGetExample:
    def test_returns_example_detail(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/example/hello-chat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["spec"]["name"] == "hello-chat"
        assert data["spec"]["runs_in"] == "standalone"
        assert "example: hello-chat" in data["text"]
        assert "ChatRouter" in data["text"]

    def test_returns_404_for_unknown_example(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/example/not-there")
        assert resp.status_code == 404
        assert "not registered" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /self/drift
# ---------------------------------------------------------------------------


class TestGetDrift:
    def test_empty_registry_reports_nothing_to_check(
        self, client: TestClient
    ) -> None:
        resp = client.get("/self/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_doc_refs"] == 0
        assert data["total_doc_guides"] == 0
        assert data["drifted"] == []
        assert data["missing_hashes"] == []
        assert "no documentation registered" in data["text"]

    def test_drifted_hashes_are_reported(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)  # placeholder hashes → drift
        resp = client.get("/self/drift")
        data = resp.json()
        assert data["total_doc_refs"] == 1
        assert data["total_doc_guides"] == 1
        assert data["doc_refs_hashed"] == 1
        assert data["doc_guides_hashed"] == 1
        kinds = {entry["kind"] for entry in data["drifted"]}
        names = {entry["name"] for entry in data["drifted"]}
        assert kinds == {"doc-ref", "doc-guide"}
        assert names == {"all-services", "chat-routing-guide"}
        for entry in data["drifted"]:
            assert entry["stored_hash"] in ("hash-1", "hash-2")
            assert entry["recomputed_hash"].startswith("1:")
        assert "drifted" in data["text"]

    def test_clean_hashes_report_no_drift(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry, with_real_hashes=True)
        resp = client.get("/self/drift")
        data = resp.json()
        assert data["drifted"] == []
        assert data["missing_hashes"] == []
        assert "clean" in data["text"]

    def test_missing_hashes_are_surfaced(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
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
        resp = client.get("/self/drift")
        data = resp.json()
        assert data["doc_refs_hashed"] == 0
        assert "doc-ref:unhashed-doc" in data["missing_hashes"]

    def test_transpiler_version_query_param_is_accepted(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        resp = client.get("/self/drift?transpiler_version=1.2.3")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


class TestDocsEndpointsConsistency:
    """Every new endpoint returns a populated ``text`` field."""

    def test_all_new_endpoints_have_text_field(
        self, client: TestClient, registry: ComponentRegistry
    ) -> None:
        _register_chat_router(registry)
        endpoints: list[tuple[str, dict[str, Any]]] = [
            ("/self/docs", {}),
            ("/self/doc/all-services", {}),
            ("/self/examples", {}),
            ("/self/example/hello-chat", {}),
            ("/self/drift", {}),
        ]
        for endpoint, _ in endpoints:
            resp = client.get(endpoint)
            assert resp.status_code == 200, (
                f"{endpoint} returned {resp.status_code}"
            )
            data = resp.json()
            assert "text" in data, f"{endpoint} missing 'text'"
            assert isinstance(data["text"], str) and len(data["text"]) > 0
