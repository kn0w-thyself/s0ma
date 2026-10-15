"""Stock keeping for the corner-shop script; nothing here mutates its input."""

from __future__ import annotations

LOW_STOCK_THRESHOLD = 5
CURRENCY_CODE = "GBP"


def add_item(stock: dict[str, int], name: str, quantity: int) -> dict[str, int]:
    """Return a copy of ``stock`` holding ``quantity`` more of ``name``."""
    updated = dict(stock)
    updated[name] = updated.get(name, 0) + quantity
    return updated


def remove_item(stock: dict[str, int], name: str, quantity: int) -> dict[str, int]:
    """Return a copy of ``stock`` holding ``quantity`` fewer of ``name``.

    An item that falls to zero is dropped rather than kept at a negative.
    """
    updated = dict(stock)
    remaining = updated.get(name, 0) - quantity
    if remaining <= 0:
        updated.pop(name, None)
    else:
        updated[name] = remaining
    return updated


def low_stock(stock: dict[str, int]) -> list[str]:
    """The names that have fallen to or below the low-stock threshold."""
    return sorted(name for name, count in stock.items() if _is_low(count))


def total_units(stock: dict[str, int]) -> int:
    """How many individual units the shop is holding altogether."""
    return sum(stock.values())


def _is_low(count: int) -> bool:
    return count <= LOW_STOCK_THRESHOLD
