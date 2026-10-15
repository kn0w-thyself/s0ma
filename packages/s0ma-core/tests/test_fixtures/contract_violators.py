"""Test fixture: components that violate their contracts.

These functions and classes are used to test that the contract
verification decorators correctly detect violations. Each entity
has a contract that it intentionally breaks.
"""

from __future__ import annotations

from s0ma.verifiers.contracts import invariant, postcondition, precondition


class Calculator:
    """A calculator with contract-decorated methods."""

    @precondition(lambda self, a, b: b != 0, "divisor must not be zero")
    def divide(self, a: float, b: float) -> float:
        """Divide a by b. Precondition: b != 0."""
        return a / b

    @postcondition(lambda result: result >= 0, "result must be non-negative")
    def absolute(self, x: float) -> float:
        """Return absolute value. Postcondition: result >= 0."""
        return abs(x)

    @postcondition(
        lambda result: result >= 0, "result must be non-negative"
    )
    def broken_absolute(self, x: float) -> float:
        """Intentionally returns negative — violates postcondition."""
        return -abs(x)

    @precondition(lambda self, x: x > 0, "input must be positive")
    @postcondition(lambda result: result > 0, "result must be positive")
    def double_positive(self, x: float) -> float:
        """Double a positive number. Both pre and post checked."""
        return x * 2


@invariant(lambda self: self.balance >= 0, "balance must be non-negative")
class BankAccount:
    """Account with an invariant: balance >= 0."""

    def __init__(self, balance: float = 0.0) -> None:
        self.balance = balance

    def deposit(self, amount: float) -> None:
        """Add funds to the account."""
        self.balance += amount

    def withdraw(self, amount: float) -> None:
        """Remove funds (may violate invariant if overdraft)."""
        self.balance -= amount


def slow_function() -> str:
    """A function that takes ~50ms — used to test performance contracts."""
    import time

    time.sleep(0.05)
    return "done"


def fast_function() -> str:
    """A function that completes quickly."""
    return "done"
