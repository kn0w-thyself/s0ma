"""Sample application one: a tiny stock ledger. Input data, never imported."""

from __future__ import annotations

from support import LOW_STOCK, shortfall


class Anomaly:
    """Something the ledger noticed and could not explain."""

    def __init__(self, item: str, reason: str) -> None:
        self.item = item
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.item}: {self.reason}"


def audit(stock: dict[str, int]) -> list[Anomaly]:
    """Every item whose count looks wrong, in name order."""
    found = []
    for item, count in sorted(stock.items()):
        if count < 0:
            found.append(Anomaly(item, "a negative count"))
        elif count < LOW_STOCK:
            found.append(Anomaly(item, f"{shortfall(count)} below the floor"))
    return found


def main() -> int:
    for anomaly in audit({"cider": 2, "damsons": -1, "pears": 40}):
        print(anomaly)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
