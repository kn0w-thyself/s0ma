"""Sample module with only private names — should pass enforcement.

Private entities (names starting with _) are not subject to
registration enforcement.
"""


class _PrivateHelper:
    """A private class — not checked by the import hook."""

    def assist(self) -> str:
        return "private assistance"


def _private_function() -> str:
    """A private function — not checked by the import hook."""
    return "private"


# Module-level constants are also not checked
_CONFIG = {"key": "value"}
PUBLIC_CONSTANT = 42  # Not a class or function, so not checked
