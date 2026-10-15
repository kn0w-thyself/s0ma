"""Core-neutral discovered-surface inputs for the 0.14 gate contract."""

from __future__ import annotations

import pytest

from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry
from s0ma.types import ComponentKind, Layer
from s0ma.verifiers import (
    DiscoveredDeclaration,
    DiscoveredSurface,
    verify_contracts,
    verify_coverage,
    verify_interoception,
)
from s0ma.verifiers.interoception import MetricsCollector


def _registry() -> ComponentRegistry:
    registry = ComponentRegistry(persist=False)
    registry.register(ComponentSpec(
        name="Modeled",
        kind=ComponentKind.FUNCTION,
        layer=Layer.DOMAIN,
        intent="A modeled declaration used by the discovery contract test",
        module_path="app.modeled",
        qualified_name="app.modeled.Modeled",
    ))
    return registry


def _surface() -> DiscoveredSurface:
    return DiscoveredSurface(declarations=(
        DiscoveredDeclaration(
            identifier="app::Modeled",
            declaration_kind="nerve",
            source_path="src/app.s0ma",
            registration_status="componentized",
        ),
        DiscoveredDeclaration(
            identifier="src/legacy.py",
            declaration_kind="python_module",
            source_path="src/legacy.py",
            registration_status="roster_adopted",
        ),
    ))


@pytest.mark.parametrize("verifier", ["contracts", "coverage", "interoception"])
def test_verifiers_fault_discovered_minus_registry(verifier: str) -> None:
    registry = _registry()
    surface = _surface()
    if verifier == "contracts":
        result = verify_contracts(registry, discovered_surface=surface)
    elif verifier == "coverage":
        result = verify_coverage(registry, discovered_surface=surface)
    else:
        result = verify_interoception(
            registry,
            collector=MetricsCollector(),
            discovered_surface=surface,
        )

    faults = [
        anomaly
        for anomaly in result.anomalies
        if anomaly.details.get("code") == "UNREGISTERED_SURFACE"
    ]
    assert len(faults) == 1
    assert faults[0].severity.name == "ERROR"
    assert faults[0].details["count"] == 1
    assert faults[0].details["exemplars"][0]["source_path"] == "src/legacy.py"


def test_componentized_canonical_identifier_resolves_to_registry_tail() -> None:
    surface = DiscoveredSurface(declarations=(
        DiscoveredDeclaration(
            identifier="app::Modeled",
            declaration_kind="nerve",
            source_path="src/app.s0ma",
            registration_status="componentized",
        ),
    ))
    result = verify_contracts(_registry(), discovered_surface=surface)
    assert not [
        anomaly
        for anomaly in result.anomalies
        if anomaly.details.get("code") == "UNREGISTERED_SURFACE"
    ]


def test_discovered_module_resolves_to_registered_module_metadata() -> None:
    registry = _registry()
    registry.register_module(
        name="app",
        layer="DOMAIN",
        version="1.0.0",
        intent="Registered module metadata for discovery matching",
    )
    surface = DiscoveredSurface(declarations=(
        DiscoveredDeclaration(
            identifier="app::__module__",
            declaration_kind="module",
            source_path="src/app.s0ma",
            registration_status="componentized",
        ),
    ))
    result = verify_contracts(registry, discovered_surface=surface)
    assert not [
        anomaly
        for anomaly in result.anomalies
        if anomaly.details.get("code") == "UNREGISTERED_SURFACE"
    ]
