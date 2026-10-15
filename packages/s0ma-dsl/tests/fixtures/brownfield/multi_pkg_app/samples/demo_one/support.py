"""Sample application one's own helpers. Input data, like its neighbour."""

LOW_STOCK = 5


def shortfall(count: int) -> int:
    """How far under the floor a count sits."""
    return max(0, LOW_STOCK - count)
