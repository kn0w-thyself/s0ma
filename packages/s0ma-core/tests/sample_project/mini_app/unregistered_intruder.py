"""Intentionally unregistered module — the sabotage test target.

This module contains a public class with NO @component or @internal
decorator. When the import hook is active in strict mode, importing
this module must raise UnregisteredComponentError.
"""


class RogueService:
    """An unregistered public class — should be caught by the import hook."""

    def infiltrate(self) -> str:
        return "I bypassed registration!"
