"""Storage adapter — simulates persistence for the mini app."""

from __future__ import annotations

from typing import Any

from s0ma.decorators import component
from s0ma.types import ComponentKind, Layer


@component(
    name="StorageAdapter",
    kind=ComponentKind.ADAPTER,
    layer=Layer.INFRASTRUCTURE,
    intent="Provides in-memory storage simulating a database for task persistence",
)
class StorageAdapter:
    """Simple in-memory storage adapter for testing."""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def save(self, key: str, value: Any) -> None:
        self._store[key] = value

    def load(self, key: str) -> Any | None:
        return self._store.get(key)

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False
