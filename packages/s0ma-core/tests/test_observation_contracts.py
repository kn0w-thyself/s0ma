"""Public adapter parity for verification, resolution, and snapshot evidence."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from s0ma.api.query_engine import QueryEngine
from s0ma.exceptions import RegistryIntegrityError
from s0ma.models import Anomaly, ComponentSpec, VerificationReport, VerificationResult
from s0ma.registry import ComponentRegistry
from s0ma.runtime import SelfInspectAdapter, self_inspect_adapter
from s0ma.self_model.interface import SelfModelInterface
from s0ma.types import AnomalyKind, AnomalySeverity, ComponentKind, Layer, VerificationScope


@pytest.fixture
def registry() -> ComponentRegistry:
    registry = ComponentRegistry(persist=False)
    registry.register(
        ComponentSpec(
            name="FixtureProvider",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Provide a fixture read operation.",
            module_path="alpha",
            qualified_name="alpha.FixtureProvider",
            module_scoped=True,
            metadata={
                "provides": ["fixture_read"],
                "provides_contracts": [
                    {
                        "name": "fixture_read",
                        "returns": "str",
                        "expects": "none",
                        "guarantees": "Returns a fixture value.",
                    }
                ],
            },
        )
    )
    return registry


def _client(registry: ComponentRegistry) -> Any:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from s0ma.api.rest import create_app

    return TestClient(create_app(registry))


def _mcp(registry: ComponentRegistry, tool: str, **arguments: Any) -> str:
    pytest.importorskip("mcp")
    from s0ma.api.mcp_server import create_mcp_server

    content, _ = asyncio.run(create_mcp_server(registry).call_tool(tool, arguments))
    return content[0].text


@pytest.mark.parametrize("outcome", ["passed", "failed", "missing", "exception", "empty"])
def test_verification_meaning_through_public_adapters(registry, monkeypatch, outcome):
    import s0ma.verifiers

    def verify(*args, **kwargs):
        if outcome == "missing":
            raise ImportError("fixture-secret")
        if outcome == "exception":
            raise RuntimeError("fixture-secret")
        return VerificationReport(
            results=[]
            if outcome == "empty"
            else [
                VerificationResult(
                    verifier_name="fixture",
                    scope=VerificationScope.STRUCTURAL,
                    anomalies=[]
                    if outcome != "failed"
                    else [
                        Anomaly(
                            kind=AnomalyKind.PHANTOM_LIMB,
                            severity=AnomalySeverity.ERROR,
                            component_name="FixtureProvider",
                            message="Fixture mismatch.",
                        )
                    ],
                )
            ],
            total_anomalies=1 if outcome == "failed" else 0,
            total_errors=1 if outcome == "failed" else 0,
        )

    monkeypatch.setattr(s0ma.verifiers, "verify_all", verify)
    status = outcome if outcome in {"passed", "failed"} else "unavailable"
    expected_pass = {"passed": True, "failed": False, "unavailable": None}[status]
    client = _client(registry)
    response = client.get("/self/health")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == status
    assert result["passed"] is expected_pass
    assert result["anomaly_count"] == (
        None if status == "unavailable" else 1 if status == "failed" else 0
    )
    texts = [
        result["text"],
        SelfModelInterface(registry).describe_system(),
        QueryEngine(registry, SelfModelInterface(registry)).query("Is the system healthy?"),
        _mcp(registry, "check_health"),
    ]
    for text in texts:
        assert f"Verification status: {status.upper()}" in text
        assert "fixture-secret" not in text
        assert "system is healthy" not in text.lower()
    if status == "unavailable":
        assert result["reason"]
        assert result["checked_at"] is None
        anomalies = client.get("/self/anomalies").json()
        assert anomalies["status"] == "unavailable"
        assert anomalies["total"] is None


@pytest.mark.parametrize("name", ["alpha::FixtureProvider", "FixtureProvider", "fixture_read"])
def test_component_resolution_through_public_adapters(registry, name):
    response = _client(registry).get(f"/self/component/{name}")
    assert response.status_code == 200
    result = response.json()
    assert result["resolved"]["component"] == "alpha::FixtureProvider"
    assert result["spec"]["name"] == "FixtureProvider"
    for text in [
        result["text"],
        SelfModelInterface(registry).describe_component(name),
        _mcp(registry, "find_component", name=name),
        QueryEngine(registry, SelfModelInterface(registry)).query(f'What is "{name}"?'),
    ]:
        assert "FixtureProvider" in text
        assert "Returns a fixture value." in text


def test_ambiguity_and_unknown_are_distinct(registry):
    spec = registry.get("FixtureProvider")
    registry.register(replace(spec, module_path="beta", qualified_name="beta.FixtureProvider"))
    for name in ["fixture_read", "FixtureProvider"]:
        response = _client(registry).get(f"/self/component/{name}")
        assert response.status_code == 409
        error = response.json()["detail"]
        assert error["code"] == "AMBIGUOUS_COMPONENT"
        assert error["candidates"] == ["alpha::FixtureProvider", "beta::FixtureProvider"]
        with pytest.raises(
            RegistryIntegrityError, match="alpha::FixtureProvider.*beta::FixtureProvider"
        ):
            SelfModelInterface(registry).describe_component(name)
        for text in [
            _mcp(registry, "find_component", name=name),
            QueryEngine(registry, SelfModelInterface(registry)).query(f'What is "{name}"?'),
        ]:
            assert "alpha::FixtureProvider" in text and "beta::FixtureProvider" in text
    response = _client(registry).get("/self/component/absent_operation")
    assert response.status_code == 404
    assert "not registered" in response.json()["detail"]


def test_rest_resolves_once_and_accepts_package_qualified_names(registry, monkeypatch):
    original = registry.resolve_component
    calls = []

    def resolve(name):
        calls.append(name)
        return original(name)

    monkeypatch.setattr(registry, "resolve_component", resolve)
    assert _client(registry).get("/self/component/fixture_read").status_code == 200
    assert calls == ["fixture_read"]
    spec = registry.get("FixtureProvider")
    registry.unregister("alpha::FixtureProvider")
    registry.register(
        replace(spec, module_path="pkg.alpha", qualified_name="pkg.alpha.FixtureProvider")
    )
    for name in ("alpha::FixtureProvider", "pkg.alpha::FixtureProvider"):
        assert (
            _client(registry).get(f"/self/component/{name}").json()["resolved"]["component"]
            == "alpha::FixtureProvider"
        )


def test_observation_filtering_and_supplied_snapshot_time(tmp_path):
    from tests.test_runtime_self_context import _write_build

    manifest = _write_build(tmp_path)
    registry = ComponentRegistry(persist=False)
    registry.register(
        ComponentSpec(
            name="submit_order",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="Observe a framework fixture.",
            is_framework=True,
        )
    )
    registry.register(
        ComponentSpec(
            name="Unrelated",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="Observe an unrelated application service.",
        )
    )
    snapshot = registry.snapshot()
    hidden = self_inspect_adapter(manifest, registry=snapshot)
    included = self_inspect_adapter(manifest, registry=snapshot, include_framework=True)
    assert hidden.handle("component submit_order")["observed"] is False
    assert included.handle("component submit_order")["observed"] is True
    assert included.context["live_health"]["captured_at"] == snapshot.snapshot_at.isoformat()
    # REST deliberately lists the whole registry; application overview text does not.
    assert _client(registry).get("/self/components").json()["total"] == 2
    assert "Unrelated" in SelfModelInterface(registry).describe_system()


@pytest.mark.parametrize(
    "module,qualified,scoped,expected",
    [
        ("alpha", "alpha.Shared", False, [True, False]),
        ("alpha", "alpha.Shared", True, [True, False]),
        ("pkg.alpha", "pkg.alpha.Shared", True, [True, False]),
        ("", "", False, [None, None]),
        ("alpha", "beta.Shared", False, [None, None]),
        ("unknown", "unknown.Shared", False, [False, False]),
    ],
)
def test_canonical_observation_identity(tmp_path, module, qualified, scoped, expected):
    from s0ma.runtime import _live_health
    from tests.test_runtime_self_context import _write_build

    components = [
        {"id": f"{name}::Shared", "module": name, "dependencies": []} for name in ("alpha", "beta")
    ]
    registry = ComponentRegistry(persist=False)
    registry.register(
        ComponentSpec(
            name="Shared",
            kind=ComponentKind.SERVICE,
            layer=Layer.INFRASTRUCTURE,
            intent="Register one fixture service.",
            module_path=module,
            qualified_name=qualified,
            module_scoped=scoped,
        )
    )
    # The overlay helper is also checked through the public adapter below.
    overlay = _live_health(registry, components)
    adapter = SelfInspectAdapter({"components": components, "live_health": overlay})
    assert [
        adapter.handle(f"component {item['id']}")["observed"] for item in components
    ] == expected
    assert overlay["lifetime"] == "snapshot"
    assert overlay["captured_at"]
    manifest = _write_build(tmp_path, {"id": "alpha::Shared", "module": "alpha"})
    answer = self_inspect_adapter(manifest, registry=registry).handle("component Shared")
    if module == "alpha" and qualified == "alpha.Shared":
        assert answer["observed"] is True


def test_explicit_refresh_and_failed_refresh_preserve_snapshots(tmp_path, monkeypatch):
    from tests.test_runtime_self_context import _write_build

    manifest = _write_build(tmp_path)
    registry = ComponentRegistry(persist=False)
    registry.register(
        ComponentSpec(
            name="submit_order",
            kind=ComponentKind.SERVICE,
            layer=Layer.APPLICATION,
            intent="Submit a fixture order.",
        )
    )
    old = self_inspect_adapter(manifest, registry=registry)
    registry.unregister("submit_order")
    new = self_inspect_adapter(manifest, registry=registry)
    assert old.handle("component submit_order")["observed"] is True
    assert new.handle("component submit_order")["observed"] is False
    captured = new.handle("describe")["live_health"]["captured_at"]

    def fail():
        raise RuntimeError("fixture-secret")

    monkeypatch.setattr(registry, "snapshot", fail)
    unavailable = self_inspect_adapter(manifest, registry=registry)
    assert unavailable.handle("component submit_order")["observed"] is None
    assert unavailable.handle("describe")["live_health"]["status"] == "unavailable"
    assert "fixture-secret" not in str(unavailable.context)
    assert new.handle("describe")["live_health"]["captured_at"] == captured
    assert old.handle("component submit_order")["observed"] is True
