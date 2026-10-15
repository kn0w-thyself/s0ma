"""Plain-text stock reports for the corner-shop script."""

from __future__ import annotations

import inventory


class StockReport:
    """A formatted view of one stock table."""

    def __init__(self, stock: dict[str, int]) -> None:
        self.stock = dict(stock)

    def lines(self) -> list[str]:
        """One ``name: count`` line per item, in alphabetical order."""
        return [f"{name}: {count}" for name, count in sorted(self.stock.items())]

    def warnings(self) -> list[str]:
        """One line per item that has fallen to the low-stock threshold."""
        return [f"low stock: {name}" for name in inventory.low_stock(self.stock)]


def render(stock: dict[str, int]) -> str:
    """Render the whole report; no date, so the same stock reads the same."""
    from textwrap import indent

    report = StockReport(stock)
    body = "\n".join([*report.lines(), *report.warnings()])
    heading = f"Stock report ({inventory.total_units(stock)} units, {inventory.CURRENCY_CODE})"
    return heading + "\n" + indent(body, "  ")
