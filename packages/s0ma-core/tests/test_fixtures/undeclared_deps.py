"""Test fixture: components with dependency declaration mismatches.

These components have import patterns that don't match their declared
dependencies. The structural verifier should detect undeclared and
phantom dependencies.
"""

from __future__ import annotations

import json  # noqa: F401 - imported but not used (for testing phantom dep detection)


def format_output(data: dict[str, object]) -> str:
    """Uses json module but component won't declare it as a dependency."""
    return json.dumps(data)


class ServiceWithHiddenDep:
    """A service that imports another component but doesn't declare it."""

    def process(self) -> str:
        return "processed"
