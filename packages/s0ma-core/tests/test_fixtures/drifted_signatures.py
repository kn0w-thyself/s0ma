"""Test fixture: components with signature mismatches.

These components have contract declarations (input_type, output_type)
that don't match their actual function signatures. The structural
verifier should detect these discrepancies.
"""

from __future__ import annotations


def process_payment(amount: float, currency: str) -> bool:
    """Claims to accept PaymentRequest and return PaymentResult,
    but actually takes float+str and returns bool."""
    return amount > 0


class DataProcessor:
    """Claims output_type is 'DataFrame' but returns dict."""

    def transform(self, data: list[str]) -> dict[str, int]:
        return {item: len(item) for item in data}
