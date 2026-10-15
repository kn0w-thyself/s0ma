"""Shared test fixtures for S0ma test suite.

Provides reusable fixtures for registry management, test isolation,
and sample component creation. The autouse fixture ensures the global
registry is reset after every test to prevent cross-test contamination.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from s0ma.models import ComponentSpec
from s0ma.registry import ComponentRegistry, reset_registry
from s0ma.types import ComponentKind, Layer
from s0ma.verifiers.contracts import reset_contract_registry
from s0ma.verifiers.interoception import reset_metrics_collector

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_global_registry() -> Generator[None, None, None]:
    """Reset the global registry after every test.

    This autouse fixture ensures no test pollutes the global registry
    for subsequent tests. It yields control to the test, then resets
    the global registry singleton.
    """
    yield
    reset_registry()
    reset_contract_registry()
    reset_metrics_collector()


@pytest.fixture()
def registry() -> ComponentRegistry:
    """A fresh in-memory registry with no persistence."""
    return ComponentRegistry(persist=False)


@pytest.fixture()
def persisted_registry(tmp_path: Path) -> Generator[ComponentRegistry, None, None]:
    """A fresh registry with SQLite persistence in a temp directory."""
    db_path = tmp_path / "test_registry.db"
    reg = ComponentRegistry(persist=True, db_path=db_path)
    yield reg
    reg.close()


@pytest.fixture()
def strict_registry() -> ComponentRegistry:
    """A fresh in-memory registry with strict dependency validation."""
    return ComponentRegistry(persist=False, strict_dependencies=True)


@pytest.fixture()
def sample_specs() -> list[ComponentSpec]:
    """A set of sample ComponentSpecs for testing.

    Creates a small dependency graph:
        UserService -> DatabaseAdapter
        UserModel (standalone)
    """
    return [
        ComponentSpec(
            name="DatabaseAdapter",
            kind=ComponentKind.ADAPTER,
            layer=Layer.INFRASTRUCTURE,
            intent="Provides database connectivity and query execution",
            module_path="myapp.adapters.database",
            qualified_name="myapp.adapters.database.DatabaseAdapter",
        ),
        ComponentSpec(
            name="UserService",
            kind=ComponentKind.SERVICE,
            layer=Layer.DOMAIN,
            intent="Manages user lifecycle including registration and authentication",
            dependencies=["DatabaseAdapter"],
            module_path="myapp.services.user",
            qualified_name="myapp.services.user.UserService",
        ),
        ComponentSpec(
            name="UserModel",
            kind=ComponentKind.MODEL,
            layer=Layer.DOMAIN,
            intent="Represents a user entity with validation invariants",
            module_path="myapp.models.user",
            qualified_name="myapp.models.user.UserModel",
        ),
    ]


@pytest.fixture()
def populated_registry(
    registry: ComponentRegistry,
    sample_specs: list[ComponentSpec],
) -> ComponentRegistry:
    """A registry pre-populated with sample components."""
    for spec in sample_specs:
        registry.register(spec)
    return registry
